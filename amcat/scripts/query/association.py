##########################################################################
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
import StringIO
import csv
import json
from django import forms
from django.core.exceptions import ValidationError
from amcat.scripts.query import QueryAction, QueryActionForm, QueryActionHandler
from amcat.tools.association import FORMATS, INTERVALS, Association
from amcat.tools.keywordsearch import SelectionSearch


def get_content_type(form):
    return form.cleaned_data["output_type"].split(";")


class AssociationForm(QueryActionForm):
    number_format = forms.ChoiceField(choices=((c, c) for c in FORMATS), required=True)
    interval = forms.ChoiceField(choices=((str(i), str(i)) for i in INTERVALS), required=False, initial="None")
    weigh = forms.BooleanField(label="Weigh for number of hits", required=False)

    graph_threshold = forms.DecimalField(label="Graph: threshold", required=False, initial=0.0)
    graph_label = forms.BooleanField(label="Graph: include association in label", required=False)

    def clean_interval(self):
        interval = self.cleaned_data["interval"]
        return None if interval == "None" else interval

    def clean(self):
        super(AssociationForm, self).clean()
        output_type, meaning = get_content_type(self)

        if self.cleaned_data["interval"] and output_type == "text/csv" and meaning == "cross":
            error_msg = "You cannot export crosstables to text/csv if an interval is specified"
            raise ValidationError(error_msg)

        return self.cleaned_data


class AssociationAction(QueryAction):
    form_class = AssociationForm

    output_types = (
        ("application/json+table;fromto", "Table (from-to)"),
        ("application/json+crosstables;cross", "Table (cross)"),
        ("text/csv;fromto", "CSV (from-to)"),
        ("text/csv;cross", "CSV (cross)"),
        ("text/csv;cross", "CSV (cross)"),
        ("application/json+image+svg+multiple;", "Graph"),
    )


    def get_association(self, form):
        selection = SelectionSearch(form)
        filters = selection.get_filters()
        queries = selection.get_queries()

        weighted = form.cleaned_data["weigh"]
        interval = form.cleaned_data["interval"]

        return Association(queries, filters, weighted=weighted, interval=interval)

    def get_fromto_table(self, association, format):
        headers, rows = association.get_table(format)
        if association.interval is None:
            return headers[1:], (r[1:] for r in rows)
        return headers, rows

    def get_formatter(self, form):
        return FORMATS[form.cleaned_data["number_format"]]

    def run(self, form):
        association = self.get_association(form)
        content_type, meaning = get_content_type(form)
        formatter = self.get_formatter(form)

        # application/json+table;fromto
        if content_type == "application/json+table" and meaning == "fromto":
            headers, rows = self.get_fromto_table(association, formatter)
            return json.dumps([headers] + list(rows), default=str)

        # application/json+table;cross
        elif content_type == "application/json+crosstables" and meaning == "cross":
            tables = association.get_crosstables(formatter)
            tables = [(interval, list(table)) for interval, table in tables]
            return json.dumps(tables, default=str)

        elif content_type == "application/json+image+svg+multiple":
            threshold = form.cleaned_data["graph_threshold"]
            include_labels = form.cleaned_data["graph_label"]
            graphs = association.get_graphs(formatter, threshold, include_labels)
            return json.dumps([(interval, graph.getHTMLSVG()) for interval, graph in graphs])

        # text/csv;fromto
        elif meaning == "fromto":
            headers, rows = self.get_fromto_table(association, formatter)

        # text/csv;cross
        elif meaning == "cross":
            # Only cross tables without intervals can be exported to CSV. Luckily,
            # AssociationForm has already filtered this case for us.
            interval, cross_table = next(iter(association.get_crosstables(formatter)))
            headers, rows = next(cross_table), list(cross_table)


        # Write table to CSV and return
        result = StringIO.StringIO()
        csvf = csv.writer(result)
        csvf.writerow(map(str, headers))
        csvf.writerows(rows)
        return result.getvalue()
