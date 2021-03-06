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
import json
from rest_framework.reverse import reverse
from rest_framework.test import APITestCase
from amcat.models import Article
from amcat.tools import amcattest


class TestArticleUploadView(APITestCase):
    def setUp(self):
        self.project = amcattest.create_test_project()
        self.user = self.project.owner
        self.url = reverse("api:article-upload") + "?format=json"

    def _post(self, data):
        return self.client.post(self.url, content_type="application/json", data=json.dumps(data))

    def test_post(self):
        self.client.login(username=self.user.username, password="test")

        response = self._post([
            {
                "date": "2011-01-01T11:11",
                "headline": "test",
                "medium": "test",
                "project": self.project.id,
                "text": "aap noot mies",
                "children": [{
                     "date": "2011-01-01T11:11",
                     "headline": "test",
                     "medium": "test",
                     "project": self.project.id,
                     "text": "aap, mies in nood",
                     "children": []
                }]
             }
        ])

        article_ids = json.loads(response.content)
        self.assertEqual(2, len(article_ids))
        self.assertEqual(201, response.status_code)

        a1 = Article.objects.get(id=article_ids[0])
        a2 = Article.objects.get(id=article_ids[1])
        self.assertEqual(a1.length, 3)
        self.assertEqual(a2.length, 4)

    def test_post_parent(self):
        article = amcattest.create_test_article()

        response = self._post([
            {
                "date": "2011-01-01T11:11",
                "headline": "test",
                "medium": "test",
                "project": self.project.id,
                "text": "aap noot mies",
                "parent": article.id,
                "children": []
             }
        ])

        new_article_id = json.loads(response.content)[0]
        new_article = Article.objects.get(id=new_article_id)

        self.assertEqual(article, new_article.parent)

