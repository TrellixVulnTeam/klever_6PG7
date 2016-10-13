#
# Copyright (c) 2014-2016 ISPRAS (http://www.ispras.ru)
# Institute for System Programming of the Russian Academy of Sciences
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import json
import tarfile
from io import BytesIO
import xml.etree.ElementTree as ETree
from xml.dom import minidom
from django.core.exceptions import ObjectDoesNotExist
from django.core.urlresolvers import reverse
from django.db.models import Q, Count
from django.utils.translation import ugettext_lazy as _
from bridge.vars import REPORT_ATTRS_DEF_VIEW, UNSAFE_LIST_DEF_VIEW, \
    SAFE_LIST_DEF_VIEW, UNKNOWN_LIST_DEF_VIEW, UNSAFE_VERDICTS, SAFE_VERDICTS
from bridge.utils import extract_tar_temp
from jobs.utils import get_resource_data
from reports.models import ReportComponent, Attr, AttrName, ReportAttr, ReportUnsafe, ReportSafe, ReportUnknown
from marks.tables import SAFE_COLOR, UNSAFE_COLOR
from marks.models import UnknownProblem, MarkUnknown
from bridge.tableHead import Header


REP_MARK_TITLES = {
    'mark_num': _('Mark'),
    'mark_verdict': _("Verdict"),
    'mark_result': _('Similarity'),
    'mark_status': _('Status'),
    'number': '№',
    'component': _('Component'),
    'marks_number': _("Number of associated marks"),
    'report_verdict': _("Total verdict"),
    'tags': _('Tags')
}

MARK_COLUMNS = ['mark_verdict', 'mark_result', 'mark_status']


def computer_description(computer):
    computer = json.loads(computer)
    data = []
    comp_name = _('Unknown')
    for comp_data in computer:
        if isinstance(comp_data, dict):
            data_name = str(next(iter(comp_data)))
            if data_name == 'node name':
                comp_name = str(comp_data[data_name])
            else:
                data.append([data_name, str(comp_data[data_name])])
    return {
        'name': comp_name,
        'data': data
    }


def get_parents(report):
    parents_data = []
    try:
        parent = ReportComponent.objects.get(id=report.parent_id)
    except ObjectDoesNotExist:
        parent = None
    while parent is not None:
        parent_attrs = []
        for rep_attr in parent.attrs.order_by('attr__name__name'):
            parent_attrs.append([rep_attr.attr.name.name, rep_attr.attr.value])
        parents_data.insert(0, {
            'title': parent.component.name,
            'href': reverse('reports:component', args=[report.root.job.pk, parent.pk]),
            'attrs': parent_attrs
        })
        try:
            parent = ReportComponent.objects.get(id=parent.parent_id)
        except ObjectDoesNotExist:
            parent = None
    return parents_data


def report_resources(report, user):
    if all(x is not None for x in [report.wall_time, report.cpu_time, report.memory]):
        rd = get_resource_data(user, report)
        return {'wall_time': rd[0], 'cpu_time': rd[1], 'memory': rd[2]}
    return None


class ReportTable(object):

    def __init__(self, user, report, view=None, view_id=None, table_type='0',
                 component_id=None, verdict=None, tag=None, problem=None, mark=None, attr=None):
        self.component_id = component_id
        self.report = report
        self.user = user
        self.type = table_type
        self.verdict = verdict
        self.tag = tag
        self.problem = problem
        self.mark = mark
        self.attr = attr
        self.columns = []
        (self.view, self.view_id) = self.__get_view(view, view_id)
        self.views = self.__views()
        self.table_data = self.__get_table_data()

    def __get_view(self, view, view_id):
        if self.type not in ['3', '4', '5', '6']:
            return None, None

        def_views = {
            '3': REPORT_ATTRS_DEF_VIEW,
            '4': UNSAFE_LIST_DEF_VIEW,
            '5': SAFE_LIST_DEF_VIEW,
            '6': UNKNOWN_LIST_DEF_VIEW,
        }

        if view is not None:
            return json.loads(view), None
        if view_id is None:
            pref_view = self.user.preferableview_set.filter(view__type=self.type)
            if len(pref_view) > 0:
                return json.loads(pref_view[0].view.view), pref_view[0].view_id
        elif view_id == 'default':
            return def_views[self.type], 'default'
        else:
            user_view = self.user.view_set.filter(pk=int(view_id), type=self.type)
            if len(user_view):
                return json.loads(user_view[0].view), user_view[0].pk
        return def_views[self.type], 'default'

    def __views(self):
        views = []
        for view in self.user.view_set.filter(type=self.type):
            views.append({
                'id': view.pk,
                'name': view.name
            })
        return views

    def __get_table_data(self):
        actions = {
            '0': self.__self_data,
            '3': self.__component_data,
            '4': self.__verdict_data,
            '5': self.__verdict_data,
            '6': self.__unknowns_data,
        }
        if self.type in actions:
            self.columns, values = actions[self.type]()
        else:
            return {}
        return {
            'header': Header(self.columns, REP_MARK_TITLES).struct,
            'values': values
        }

    def __self_data(self):
        columns = []
        values = []
        for rep_attr in self.report.attrs.order_by('id'):
            columns.append(rep_attr.attr.name.name)
            values.append(rep_attr.attr.value)
        return columns, values

    def __component_data(self):
        data = {}
        components = {}
        columns = []
        component_filters = {'parent': self.report}
        if 'component' in self.view['filters']:
            component_filters[
                'component__name__' + self.view['filters']['component']['type']
                ] = self.view['filters']['component']['value']
        finish_dates = {}
        for report in ReportComponent.objects.filter(**component_filters):
            for rep_attr in report.attrs.order_by('id'):
                if rep_attr.attr.name.name not in data:
                    columns.append(rep_attr.attr.name.name)
                    data[rep_attr.attr.name.name] = {}
                data[rep_attr.attr.name.name][report.pk] = rep_attr.attr.value
                if self.view['order'][0] == 'date':
                    if report.finish_date is not None:
                        finish_dates[report.pk] = report.finish_date
            components[report.pk] = report.component

        comp_data = []
        for pk in components:
            if self.view['order'][0] == 'component':
                comp_data.append((components[pk].name, {
                    'pk': pk,
                    'component': components[pk]
                }))
            elif self.view['order'][0] == 'date':
                if pk in finish_dates:
                    comp_data.append((finish_dates[pk], {
                        'pk': pk,
                        'component': components[pk]
                    }))
            else:
                attr_val = '-'
                if self.view['order'][0] in data and pk in data[self.view['order'][0]]:
                    attr_val = data[self.view['order'][0]][pk]
                comp_data.append((attr_val, {
                    'pk': pk,
                    'component': components[pk]
                }))
        sorted_components = []
        for name, dt in sorted(comp_data, key=lambda x: x[0]):
            sorted_components.append(dt)
        if self.view['order'] is not None and self.view['order'][1] == 'up':
            sorted_components = list(reversed(sorted_components))

        values_data = []
        for comp_data in sorted_components:
            values_row = []
            for col in columns:
                cell_val = '-'
                if comp_data['pk'] in data[col]:
                    cell_val = data[col][comp_data['pk']]
                values_row.append(cell_val)
                if not self.__filter_attr(col, cell_val):
                    break
            else:
                values_data.append({
                    'pk': comp_data['pk'],
                    'component': comp_data['component'],
                    'attrs': values_row
                })
        columns.insert(0, 'component')
        return columns, values_data

    def __verdict_data(self):
        list_types = {
            '4': 'unsafe',
            '5': 'safe',
        }
        if self.type not in list_types:
            return None, None

        data = {}

        columns = ['number']
        for col in self.view['columns']:
            if self.verdict is not None and col == 'report_verdict':
                continue
            columns.append(col)

        if self.verdict is not None:
            leaf_filter = {list_types[self.type] + '__verdict': self.verdict}
            leaves_set = self.report.leaves.filter(Q(**leaf_filter) & ~Q(**{list_types[self.type]: None}))
        elif self.mark is not None:
            leaf_filter = {list_types[self.type] + '__markreport_set__mark': self.mark}
            leaves_set = self.report.leaves.filter(**leaf_filter).distinct().filter(~Q(**{list_types[self.type]: None}))
        elif self.attr is not None:
            leaf_filter = {list_types[self.type] + '__attrs__attr': self.attr}
            leaves_set = self.report.leaves.filter(**leaf_filter).distinct().filter(~Q(**{list_types[self.type]: None}))
        else:
            leaves_set = self.report.leaves.filter(~Q(**{list_types[self.type]: None}))

        for leaf in leaves_set:
            report = getattr(leaf, list_types[self.type])
            if not self.__has_tag(report):
                continue
            for rep_attr in report.attrs.order_by('id'):
                if rep_attr.attr.name.name not in data:
                    columns.append(rep_attr.attr.name.name)
                    data[rep_attr.attr.name.name] = {}
                data[rep_attr.attr.name.name][report] = rep_attr.attr.value

        reports_ordered = []
        if 'order' in self.view and self.view['order'][0] in data:
            for report in data[self.view['order'][0]]:
                reports_ordered.append(
                    (data[self.view['order'][0]][report], report)
                )
            reports_ordered = [x[1] for x in sorted(reports_ordered, key=lambda x: x[0])]
        else:
            for attr in data:
                for report in data[attr]:
                    if report not in reports_ordered:
                        reports_ordered.append(report)
            reports_ordered = sorted(reports_ordered, key=lambda x: x.pk)
        if 'order' in self.view and self.view['order'][1] == 'up':
            reports_ordered = list(reversed(reports_ordered))

        cnt = 1
        values_data = []
        for report in reports_ordered:
            values_row = []
            for col in columns:
                val = '-'
                href = None
                color = None
                if col in data and report in data[col]:
                    val = data[col][report]
                    if not self.__filter_attr(col, val):
                        break
                elif col == 'number':
                    val = cnt
                    href = reverse('reports:leaf', args=[list_types[self.type], report.pk])
                elif col == 'marks_number':
                    broken = 0
                    num_of_connects = len(report.markreport_set.all())
                    if list_types[self.type] == 'unsafe':
                        broken = len(report.markreport_set.filter(broken=True))
                    if broken > 0:
                        val = _('%(all)s (%(broken)s are broken)') % {
                            'all': num_of_connects,
                            'broken': broken
                        }
                    else:
                        val = num_of_connects
                elif col == 'report_verdict':
                    if list_types[self.type] == 'unsafe':
                        for uns in UNSAFE_VERDICTS:
                            if uns[0] == report.verdict:
                                val = uns[1]
                                break
                        color = UNSAFE_COLOR[report.verdict]
                    else:
                        for s in SAFE_VERDICTS:
                            if s[0] == report.verdict:
                                val = s[1]
                                break
                        color = SAFE_COLOR[report.verdict]
                elif col == 'tags':
                    tags = []
                    for t in report.tags.filter(number__gt=0).order_by('tag__tag'):
                        tags.append(t.tag.tag)
                    if len(tags) > 0:
                        val = '; '.join(tags)
                values_row.append({
                    'value': val,
                    'color': color,
                    'href': href
                })
            else:
                cnt += 1
                values_data.append(values_row)
        return columns, values_data

    def __has_tag(self, report):
        if self.tag is None:
            return True
        has_tag = False
        if self.type == '4':  # unsafe
            for mark_rep in report.markreport_set.all():
                try:
                    mark_rep.mark.versions\
                        .order_by('-version')[0].tags.get(tag=self.tag)
                    has_tag = True
                except ObjectDoesNotExist:
                    continue
        elif self.type == '5':  # safe
            for mark_rep in report.markreport_set.all():
                try:
                    mark_rep.mark.versions\
                        .order_by('-version')[0].tags.get(tag=self.tag)
                    has_tag = True
                except ObjectDoesNotExist:
                    continue
        return has_tag

    def __unknowns_data(self):
        data = {}
        components = {}
        filters = {}
        if self.component_id is not None:
            filters['unknown__component_id'] = int(self.component_id)
        if 'component' in self.view['filters'] \
                and self.view['filters']['component']['type'] in ['iexact', 'istartswith', 'icontains']:
            ftype = 'unknown__component__name__%s' % self.view['filters']['component']['type']
            filters[ftype] = self.view['filters']['component']['value']
        if isinstance(self.problem, UnknownProblem):
            leaf_set = self.report.leaves.filter(unknown__markreport_set__problem=self.problem).distinct()\
                .filter(~Q(unknown=None) & Q(**filters))
        elif isinstance(self.mark, MarkUnknown):
            leaf_set = self.report.leaves.filter(unknown__markreport_set__mark=self.mark).distinct()\
                .filter(~Q(unknown=None) & Q(**filters))
        elif self.attr is not None:
            leaf_set = self.report.leaves.filter(unknown__attrs__attr=self.attr).distinct()\
                .filter(~Q(unknown=None) & Q(**filters))
        else:
            if self.problem == 0:
                filters['mr_set_len'] = 0
            leaf_set = self.report.leaves.annotate(mr_set_len=Count('unknown__markreport_set'))\
                .filter(~Q(unknown=None) & Q(**filters))
        columns = ['component']
        for leaf in leaf_set:
            report = leaf.unknown
            for rep_attr in report.attrs.order_by('id'):
                if rep_attr.attr.name.name not in data:
                    columns.append(rep_attr.attr.name.name)
                    data[rep_attr.attr.name.name] = {}
                data[rep_attr.attr.name.name][report.pk] = rep_attr.attr.value
            components[report.pk] = report.component.name

        report_ids = []
        if 'order' in self.view and self.view['order'][0] in data:
            ids_ordered = []
            for rep_id in data[self.view['order'][0]]:
                ids_ordered.append((data[self.view['order'][0]][rep_id], rep_id))
            report_ids = [x[1] for x in sorted(ids_ordered, key=lambda x: x[0])]
        else:
            comp_data = []
            for pk in components:
                comp_data.append((components[pk], pk))
            for name, rep_id in sorted(comp_data, key=lambda x: x[0]):
                report_ids.append(rep_id)
        if 'order' in self.view and self.view['order'][1] == 'up':
            report_ids = list(reversed(report_ids))

        values_data = []
        for rep_id in report_ids:
            values_row = []
            for col in columns:
                val = '-'
                href = None
                if col in data and rep_id in data[col]:
                    val = data[col][rep_id]
                    if not self.__filter_attr(col, val):
                        break
                elif col == 'component':
                    val = components[rep_id]
                    href = reverse('reports:leaf', args=['unknown', rep_id])
                values_row.append({
                    'value': val,
                    'href': href
                })
            else:
                values_data.append(values_row)
        return columns, values_data

    def __filter_attr(self, attribute, value):
        if 'attr' in self.view['filters']:

            fattr = self.view['filters']['attr']['attr']
            fvalue = self.view['filters']['attr']['value']
            ftype = self.view['filters']['attr']['type']
            if fattr is not None and fattr.lower() == attribute.lower():
                if ftype == 'iexact' and fvalue.lower() != value.lower():
                    return False
                elif ftype == 'istartswith' and \
                        not value.lower().startswith(fvalue.lower()):
                    return False
        return True


def save_attrs(report, attrs):
    def children(name, val):
        attr_data = []
        if isinstance(val, list):
            for v in val:
                if isinstance(v, dict):
                    nextname = next(iter(v))
                    for n in children(nextname.replace(':', '_'), v[nextname]):
                        if len(name) == 0:
                            new_id = n[0]
                        else:
                            new_id = "%s:%s" % (name, n[0])
                        attr_data.append((new_id, n[1]))
        elif isinstance(val, str):
            attr_data = [(name, val)]
        return attr_data

    if not isinstance(attrs, list):
        return []
    attrdata = AttrData()
    attrorder = []
    for attr, value in children('', attrs):
        attrorder.append(attr)
        attrdata.add(report.pk, attr, value)
    attrdata.upload()
    return attrorder


class AttrData(object):
    def __init__(self):
        self._data = []
        self._name = {}
        self._attrs = {}

    def add(self, report_id, name, value):
        self._data.append((report_id, name, value))
        if name not in self._name:
            self._name[name] = None
        if (name, value) not in self._attrs:
            self._attrs[(name, value)] = None

    def upload(self):
        self.__upload_names()
        self.__upload_attrs()
        ReportAttr.objects.bulk_create(
            list(ReportAttr(report_id=d[0], attr=self._attrs[(d[1], d[2])]) for d in self._data)
        )
        self.__init__()

    def __upload_names(self):
        for name in self._name:
            self._name[name] = AttrName.objects.get_or_create(name=name)[0]

    def __upload_attrs(self):
        for attr in self._attrs:
            if attr[0] in self._name:
                self._attrs[attr] = Attr.objects.get_or_create(name=self._name[attr[0]], value=attr[1])[0]


class DownloadFilesForCompetition(object):
    def __init__(self, job, filters):
        self.name = 'svcomp.tar.gz'
        self.job = job
        self.filters = filters
        self.xml_root = None
        self.prp_file_added = False
        self.memory = BytesIO()
        self.__get_archive()
        self.memory.flush()
        self.memory.seek(0)

    def __get_archive(self):
        with tarfile.open(fileobj=self.memory, mode='w:gz', encoding='utf8') as tarobj:
            for f_t in self.filters:
                if f_t == 'u':
                    self.__add_unsafes(tarobj)
                elif f_t == 's':
                    self.__add_safes(tarobj)
                elif isinstance(f_t, list):
                    self.__add_unknowns(tarobj, f_t)
            if self.xml_root is None:
                raise ValueError('There are no filters')
            t = tarfile.TarInfo('benchmark.xml')
            xml_inmem = BytesIO(
                minidom.parseString(ETree.tostring(self.xml_root, 'utf-8')).toprettyxml(indent="  ").encode('utf8')
            )
            t.size = xml_inmem.seek(0, 2)
            xml_inmem.seek(0)
            tarobj.addfile(t, xml_inmem)
            tarobj.close()

    def __add_unsafes(self, tarobj):
        cnt = 1
        u_ids_in_use = []
        for u in ReportUnsafe.objects.filter(root__job=self.job):
            parent = ReportComponent.objects.get(id=u.parent_id)
            if parent.parent is None or parent.archive is None:
                continue
            ver_obj = ''
            ver_rule = ''
            for u_a in u.attrs.all():
                if u_a.attr.name.name == 'Verification object':
                    ver_obj = u_a.attr.value.replace('/', '-').replace('~', '-').replace('.ko', '')
                elif u_a.attr.name.name == 'Rule specification':
                    ver_rule = u_a.attr.value.replace(':', '-')
            u_id = "Unsafes/u__%s__%s.cil.i" % (ver_rule, ver_obj)
            if u_id in u_ids_in_use:
                u_id = "Unsafes/u__%s__%s__%s.cil.i" % (ver_rule, ver_obj, cnt)
                cnt += 1
            self.__add_cil_file(parent.archive, tarobj, u_id)
            new_elem = ETree.Element('include')
            new_elem.text = u_id
            self.xml_root.find('tasks').append(new_elem)
            u_ids_in_use.append(u_id)

    def __add_safes(self, tarobj):
        cnt = 1
        u_ids_in_use = []
        for s in ReportSafe.objects.filter(root__job=self.job):
            parent = ReportComponent.objects.get(id=s.parent_id)
            if parent.parent is None or parent.archive is None:
                continue
            ver_obj = ''
            ver_rule = ''
            for u_a in s.attrs.all():
                if u_a.attr.name.name == 'Verification object':
                    ver_obj = u_a.attr.value.replace('/', '-').replace('~', '-').replace('.ko', '')
                elif u_a.attr.name.name == 'Rule specification':
                    ver_rule = u_a.attr.value.replace(':', '-')
            s_id = "Safes/s__%s__%s.cil.i" % (ver_rule, ver_obj)
            if s_id in u_ids_in_use:
                s_id = "Safes/s__%s__%s__%s.cil.i" % (ver_rule, ver_obj, cnt)
                cnt += 1
            self.__add_cil_file(parent.archive, tarobj, s_id)
            new_elem = ETree.Element('include')
            new_elem.text = s_id
            self.xml_root.find('tasks').append(new_elem)
            u_ids_in_use.append(s_id)

    def __add_unknowns(self, tarobj, problems):
        cnt = 1
        u_ids_in_use = []
        if len(problems) > 0:
            unknowns = []
            for problem in problems:
                comp_id, problem_id = problem.split('_')[0:2]
                unknowns.extend(list(ReportUnknown.objects.filter(
                    root__job=self.job, markreport_set__problem_id=problem_id, component_id=comp_id
                )))
        else:
            unknowns = ReportUnknown.objects.filter(root__job=self.job)
        for u in unknowns:
            parent = ReportComponent.objects.get(id=u.parent_id)
            if parent.parent is None or parent.archive is None:
                continue
            ver_obj = ''
            ver_rule = ''
            for u_a in u.attrs.all():
                if u_a.attr.name.name == 'Verification object':
                    ver_obj = u_a.attr.value.replace('/', '-').replace('~', '-').replace('.ko', '')
                elif u_a.attr.name.name == 'Rule specification':
                    ver_rule = u_a.attr.value.replace(':', '-')
            u_id = "Unknowns/f__%s__%s.cil.i" % (ver_rule, ver_obj)
            if u_id in u_ids_in_use:
                u_id = "Unknowns/f__%s__%s__%s.cil.i" % (ver_rule, ver_obj, cnt)
                cnt += 1
            self.__add_cil_file(parent.archive, tarobj, u_id)
            new_elem = ETree.Element('include')
            new_elem.text = u_id
            self.xml_root.find('tasks').append(new_elem)
            u_ids_in_use.append(u_id)

    def __add_cil_file(self, f, tarobj, fpath):
        extracted_tar = extract_tar_temp(f.file)
        files_dir = extracted_tar.name
        with open(os.path.join(files_dir, 'benchmark.xml'), encoding='utf8') as fp:
            xml_root = ETree.fromstring(fp.read())
            cil_file = xml_root.find('tasks').find('include').text
        if self.xml_root is None:
            self.xml_root = xml_root
            self.xml_root.find('tasks').clear()

        with open(os.path.join(files_dir, cil_file), mode='rb') as fp:
            t = tarfile.TarInfo(fpath)
            t.size = fp.seek(0, 2)
            fp.seek(0)
            tarobj.addfile(t, fp)
        if not self.prp_file_added:
            with open(os.path.join(files_dir, 'unreach-call.prp'), mode='rb') as fp:
                t = tarfile.TarInfo('unreach-call.prp')
                t.size = fp.seek(0, 2)
                fp.seek(0)
                tarobj.addfile(t, fp)
                self.prp_file_added = True
