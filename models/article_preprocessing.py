###########################################################################
#          (C) Vrije Universiteit, Amsterdam (the Netherlands)            #
#                                                                         #
# This file is part of AmCAT - The Amsterdam Content Analysis Toolkit     #
#                                                                         #
# AmCAT is free software: you can redistribute it and/or modify it under  #
# the terms of the GNU Affero General Public License as published by the  #
# Free Software Foundation, either version 3 of the License, or (at your  #
# option) any later version.                                              #
#                                                                         #
# AmCAT is distributed in the hope that it will be useful, but WITHOUT    #
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or   #
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public     #
# License for more details.                                               #
#                                                                         #
# You should have received a copy of the GNU Affero General Public        #
# License along with AmCAT.  If not, see <http://www.gnu.org/licenses/>.  #
###########################################################################

"""
Model module for the Preprocessing queue

Articles on the preprocessing queue need to be checked to see if preprocessing
needs to be done.

See http://code.google.com/p/amcat/wiki/Preprocessing
"""

from __future__ import unicode_literals, print_function, absolute_import

from django.db import models

from amcat.tools.model import AmcatModel
from amcat.tools import dbtoolkit
from amcat.tools.djangotoolkit import receiver
from amcat.models.article import Article
from amcat.models.articleset import ArticleSetArticle, ArticleSet
from amcat.models.analysis import Analysis, Token, Triple, Pos, Relation
from amcat.models.project import Project
from amcat.models.word import Word
from amcat.models.sentence import Sentence
from amcat.tools.djangotoolkit import get_or_create

from django.db.models.signals import post_save, post_delete
from django.db import connection
from django.db.models import Q
from django.db import transaction

import logging; log = logging.getLogger(__name__)

class ArticlePreprocessing(AmcatModel):
    """
    An article on the Preprocessing Queue needs to be checked for preprocessing
    """

    id = models.AutoField(primary_key=True)
    article = models.ForeignKey(Article)

    class Meta():
        db_table = 'articles_preprocessing_queue'
        app_label = 'amcat'

    @classmethod
    def narticles_in_queue(cls, project):
        # subqueries for direct and indirect (via set) articles
        direct = Article.objects.filter(project=project).values("id")
        indirect = (ArticleSetArticle.objects.filter(articleset__project=project)
                    .values("article"))
        q = ArticlePreprocessing.objects.filter(Q(article__in=direct)
                                                | Q(article__in=indirect))
        # add count(distinct) manually - maybe possible through aggregate?
        q = q.extra(select=dict(n="count(distinct article_id)")).values_list("n")
        return q[0][0]




class ArticleAnalysis(AmcatModel):
    """
    The Article Analysis table keeps track of which articles are / need to be preprocessed
    """

    id = models.AutoField(primary_key=True, db_column="article_analysis_id")

    article = models.ForeignKey(Article)
    analysis = models.ForeignKey(Analysis)
    prepared = models.BooleanField(default=False)
    started = models.BooleanField(default=False)
    done = models.BooleanField(default=False)
    delete = models.BooleanField(default=False)

    class Meta():
        db_table = 'articles_analyses'
        app_label = 'amcat'
        unique_together = ('article', 'analysis')


    @transaction.commit_on_success
    def store_analysis(self, tokens, triples=None):
        """
        Store the given tokens and triples for this articleanalysis, setting
        it to done=True if stored succesfully.
        """
        if self.done: raise Exception("Cannot store analyses when already done")
        tokens = dict((t.position, self._create_token(t)) for t in tokens)
        if triples:
            for triple in triples:
                rel = get_or_create(Relation, label=triple.relation)
                print(">>>>>>>>>", rel)
                Triple.objects.create(analysis=self.analysis, relation=rel,
                                      parent=tokens[triple.parent],
                                      child=tokens[triple.child])
        self.done = True
        self.save()

    def _create_token(self, token):
        """Create a Token from a amcat.nlp.analysisscript.Token object and an analysis"""
        w = Word.get_or_create(self.analysis.language, token.lemma, token.pos, token.word)
        p = get_or_create(Pos, major=token.major, minor=token.minor, pos=token.pos)
        s = Sentence.objects.get(pk=token.sentence_id)
        return Token.objects.create(sentence=s, position=token.position,
                                    analysis=self.analysis, word=w, pos=p)

class ProjectAnalysis(AmcatModel):
    """
    Explicit many-to-many projects - analyses. Hopefully this can be removed
    when prefetch_related hits the main branch.
    """
    id = models.AutoField(primary_key=True)
    project = models.ForeignKey(Project)
    analysis = models.ForeignKey(Analysis)

    class Meta():
        app_label = 'amcat'
        db_table = "projects_analyses"
        unique_together = ('project', 'analysis')

    def narticles(self, **filter):
        # TODO: this is not very efficient for large projects!
        aids = set(self.project.get_all_articles())
        q = ArticleAnalysis.objects.filter(article__in=aids, analysis=self.analysis)
        if filter: q = q.filter(**filter)
        return q.count()


# Signal handlers to make sure the article preprocessing queue is filled
def add_to_queue(*aids):
    for aid in aids:
        ArticlePreprocessing.objects.create(article_id = aid)

@receiver([post_save, post_delete], Article)
def handle_article(sender, instance, **kargs):
    add_to_queue(instance.id)

@receiver([post_save, post_delete], ArticleSetArticle)
def handle_articlesetarticle(sender, instance, **kargs):
    add_to_queue(instance.article_id)

@receiver([post_save], Project)
def handle_project(sender, instance, **kargs):
    add_to_queue(*instance.get_all_articles())

@receiver([post_save, post_delete], ProjectAnalysis)
def handle_projectanalysis(sender, instance, **kargs):
    add_to_queue(*instance.project.get_all_articles())

@receiver([post_save], ArticleSet)
def handle_articleset(sender, instance, **kargs):
    add_to_queue(*(a.id for a in instance.articles.all().only("id")))


###########################################################################
#                          U N I T   T E S T S                            #
###########################################################################

from amcat.tools import amcattest

class TestArticlePreprocessing(amcattest.PolicyTestCase):

    def test_narticles_in_queue(self):
        # articles added to a project are on the queue
        p = amcattest.create_test_project()
        self.assertEqual(ArticlePreprocessing.narticles_in_queue(p), 0)
        [amcattest.create_test_article(project=p) for _i in range(10)]
        self.assertEqual(ArticlePreprocessing.narticles_in_queue(p), 10)

        # articles added to a set in the project are on the queue
        arts = [amcattest.create_test_article() for _i in range(10)]
        s = amcattest.create_test_set(project=p)
        self.assertEqual(ArticlePreprocessing.narticles_in_queue(p), 10)
        map(s.add, arts)
        self.assertEqual(ArticlePreprocessing.narticles_in_queue(p), 20)

    def test_article_trigger(self):
        """Is a created or update article in the queue?"""
        self._flush_queue()
        a = amcattest.create_test_article()
        self.assertIn(a.id,  self._all_articles())

        self._flush_queue()
        self.assertNotIn(a.id,  self._all_articles())
        a.headline = "bla bla"
        a.save()
        self.assertIn(a.id,  self._all_articles())


    def test_articleset_triggers(self):
        """Is a article added/removed from a set in the queue?"""

        a = amcattest.create_test_article()
        aset = amcattest.create_test_set()
        self._flush_queue()
        self.assertNotIn(a.id,  self._all_articles())

        aset.add(a)
        self.assertIn(a.id,  self._all_articles())

        self._flush_queue()
        aset.remove(a)
        self.assertIn(a.id, self._all_articles())

        self._flush_queue()
        aid = a.id
        a.delete()
        self.assertIn(aid, self._all_articles())


        b = amcattest.create_test_article()
        aset.add(b)
        self._flush_queue()
        aset.project = amcattest.create_test_project()
        aset.save()
        self.assertIn(b.id, self._all_articles())

    def test_project_triggers(self):
        """Check trigger on project (de)activation and analyses being added/removed from project?"""

        a,b = [amcattest.create_test_article() for _i in range(2)]
        s = amcattest.create_test_set(project=a.project)
        self.assertNotEqual(a.project, b.project)
        s.add(b)

        self._flush_queue()
        a.project.active=True
        a.project.save()
        self.assertIn(a.id, self._all_articles())
        self.assertIn(b.id, self._all_articles())

        self._flush_queue()
        n = amcattest.create_test_analysis()
        ProjectAnalysis.objects.create(project=a.project, analysis=n)
        self.assertIn(a.id, self._all_articles())
        self.assertIn(b.id, self._all_articles())




    @classmethod
    def _flush_queue(cls):
        """Flush the articles queue"""
        for sa in list(ArticlePreprocessing.objects.all()): sa.delete()

    @classmethod
    def _all_articles(cls):
        """List all articles on the queue"""
        return set([sa.article_id for sa in ArticlePreprocessing.objects.all()])

    def test_store_tokens(self):
        s = amcattest.create_test_sentence()
        a = amcattest.create_test_analysis()
        aa = ArticleAnalysis.objects.create(article=s.article, analysis=a)
        t1 = amcattest.create_analysis_token(sentence_id=s.id)
        aa.store_analysis(tokens=[t1])
        aa = ArticleAnalysis.objects.get(pk=aa.id)
        self.assertEqual(aa.done,  True)
        token, = list(Token.objects.filter(sentence=s, analysis=a))
        self.assertEqual(token.word.word, t1.word)
        self.assertRaises(aa.store_analysis, tokens=[t1])

    def test_store_triples(self):
        from amcat.nlp import analysisscript
        s = amcattest.create_test_sentence()
        a = amcattest.create_test_analysis()
        aa = ArticleAnalysis.objects.create(article=s.article, analysis=a)
        t1 = amcattest.create_analysis_token(sentence_id=s.id, position=1)
        t2 = amcattest.create_analysis_token(sentence_id=s.id, word="x")
        tr = analysisscript.Triple(s.id, parent=t1.position, child=t2.position, relation='su')
        aa.store_analysis(tokens=[t1, t2], triples=[tr])
        aa = ArticleAnalysis.objects.get(pk=aa.id)
        triple, = list(Triple.objects.filter(analysis=a, parent__sentence=s))
        self.assertEqual(triple.parent.word.word, t1.word)
        self.assertEqual(triple.child.word.lemma.lemma, t2.lemma)

if __name__ == '__main__':

    t = TestArticlePreprocessing()
    t._flush_queue()

    a = amcattest.create_test_article()
    print(a.id, t._all_articles())
