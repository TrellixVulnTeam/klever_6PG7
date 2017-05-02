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

import json
from io import BytesIO
from urllib.parse import quote
from wsgiref.util import FileWrapper

from django.contrib.auth.decorators import login_required
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.core.urlresolvers import reverse
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect, StreamingHttpResponse
from django.shortcuts import render
from django.utils.translation import ugettext as _, activate, string_concat
from django.template.defaulttags import register

from tools.profiling import unparallel_group
from bridge.vars import JOB_STATUS, UNKNOWN_ERROR, SAFE_VERDICTS, UNSAFE_VERDICTS, COMPARE_VERDICT
from bridge.utils import logger, ArchiveFileContent, BridgeException, BridgeErrorResponse
from jobs.ViewJobData import ViewJobData
from jobs.utils import JobAccess
from jobs.models import Job
from marks.models import UnsafeTag, SafeTag, MarkSafe, MarkUnsafe, MarkUnknown, UnknownProblem
from marks.utils import MarkAccess
from marks.tables import ReportMarkTable, MarkData
from marks.tags import TagsInfo
from service.models import Task

import reports.utils
import reports.models
from reports.UploadReport import UploadReport
from reports.etv import GetSource, GetETV
from reports.comparison import CompareTree, ComparisonTableData, ComparisonData, can_compare


# These filters are used for visualization component specific data. They should not be used for any other purposes.
@register.filter
def get_dict_val(d, key):
    return d.get(key)


@register.filter
def sort_list(l):
    return sorted(l)


@register.filter
def sort_bugs_list(l):
    return sorted(l, key=lambda bug: bug[12:].lstrip('~'))


@register.filter
def calculate_test_stats(test_results):
    test_stats = {
        "passed tests": 0,
        "failed tests": 0,
        "missed comments": 0,
        "excessive comments": 0,
        "tests": 0
    }

    for result in test_results.values():
        test_stats["tests"] += 1
        if result["ideal verdict"] == result["verification status"]:
            test_stats["passed tests"] += 1
            if result["comment"]:
                test_stats["excessive comments"] += 1
        else:
            test_stats["failed tests"] += 1
            if not result["comment"]:
                test_stats["missed comments"] += 1

    return test_stats


@register.filter
def calculate_validation_stats(validation_results):
    validation_stats = {
        "found bug before fix and safe after fix": 0,
        "found bug before fix and non-safe after fix": 0,
        "found non-bug before fix and safe after fix": 0,
        "found non-bug before fix and non-safe after fix": 0,
        "missed comments": 0,
        "excessive comments": 0,
        "bugs": 0
    }

    for result in validation_results.values():
        validation_stats["bugs"] += 1

        is_found_bug_before_fix = False

        if result["before fix"]:
            if result["before fix"]["verification status"] == "unsafe":
                is_found_bug_before_fix = True
                if result["before fix"]["comment"]:
                    validation_stats["excessive comments"] += 1
            elif not result["before fix"]["comment"]:
                validation_stats["missed comments"] += 1

        is_found_safe_after_fix = False

        if result["after fix"]:
            if result["after fix"]["verification status"] == "safe":
                is_found_safe_after_fix = True
                if result["after fix"]["comment"]:
                    validation_stats["excessive comments"] += 1
            elif not result["after fix"]["comment"]:
                validation_stats["missed comments"] += 1

        if is_found_bug_before_fix:
            if is_found_safe_after_fix:
                validation_stats["found bug before fix and safe after fix"] += 1
            else:
                validation_stats["found bug before fix and non-safe after fix"] += 1
        else:
            if is_found_safe_after_fix:
                validation_stats["found non-bug before fix and safe after fix"] += 1
            else:
                validation_stats["found non-bug before fix and non-safe after fix"] += 1

    return validation_stats


@login_required
@unparallel_group(['ReportComponent'])
def report_component(request, job_id, report_id):
    activate(request.user.extended.language)

    try:
        job = Job.objects.get(pk=int(job_id))
    except ObjectDoesNotExist:
        return BridgeErrorResponse(404)

    if not JobAccess(request.user, job).can_view():
        return BridgeErrorResponse(400)
    try:
        report = reports.models.ReportComponent.objects.get(pk=int(report_id))
    except ObjectDoesNotExist:
        return BridgeErrorResponse(504)

    duration = None
    status = 1
    if report.finish_date is not None:
        duration = report.finish_date - report.start_date
        status = 2

    view_args = [request.user, report]
    report_attrs_data = [request.user, report]
    if request.method == 'POST':
        view_type = request.POST.get('view_type', None)
        if view_type == '2':
            view_args.append(request.POST.get('view', None))
            view_args.append(request.POST.get('view_id', None))
        elif view_type == '3':
            report_attrs_data.append(request.POST.get('view', None))
            report_attrs_data.append(request.POST.get('view_id', None))

    unknown_href = None
    try:
        unknown_href = reverse('reports:unknown', args=[
            reports.models.ReportUnknown.objects.get(parent=report, component=report.component).pk
        ])
        status = 3
    except ObjectDoesNotExist:
        pass
    except MultipleObjectsReturned:
        status = 4

    report_data = None
    if report.data:
        try:
            with report.data.file as fp:
                report_data = json.loads(fp.read().decode('utf8'))
        except Exception as e:
            logger.exception("Json parsing error: %s" % e, stack_info=True)

    return render(
        request,
        'reports/ReportMain.html',
        {
            'report': report,
            'duration': duration,
            'resources': reports.utils.report_resources(report, request.user),
            'computer': reports.utils.computer_description(report.computer.description),
            'reportdata': ViewJobData(*view_args),
            'parents': reports.utils.get_parents(report),
            'SelfAttrsData': reports.utils.ReportTable(*report_attrs_data).table_data,
            'TableData': reports.utils.ReportTable(*report_attrs_data, table_type='3'),
            'status': status,
            'unknown': unknown_href,
            'data': report_data
        }
    )


@login_required
@unparallel_group(['ReportComponent', 'ReportSafe', 'ReportUnsafe', 'ReportUnknown'])
def report_list(request, report_id, ltype, component_id=None,
                verdict=None, tag=None, problem=None, mark=None, attr=None):
    activate(request.user.extended.language)

    try:
        report = reports.models.ReportComponent.objects.get(pk=int(report_id))
    except ObjectDoesNotExist:
        return BridgeErrorResponse(504)

    if not JobAccess(request.user, report.root.job).can_view():
        return BridgeErrorResponse(400)

    list_types = {
        'unsafes': '4',
        'safes': '5',
        'unknowns': '6'
    }

    if ltype == 'safes':
        title = _("All safes")
        if tag is not None:
            title = string_concat(_("Safes"), ': ', tag)
        elif verdict is not None:
            for s in SAFE_VERDICTS:
                if s[0] == verdict:
                    title = string_concat(_("Safes"), ': ', s[1])
                    break
        elif mark is not None:
            title = _('Safes marked by')
        elif attr is not None:
            title = _('Safes where %(a_name)s is %(a_val)s') % {'a_name': attr.name.name, 'a_val': attr.value}
    elif ltype == 'unsafes':
        title = _("All unsafes")
        if tag is not None:
            title = string_concat(_("Unsafes"), ': ', tag)
        elif verdict is not None:
            for s in UNSAFE_VERDICTS:
                if s[0] == verdict:
                    title = string_concat(_("Unsafes"), ': ', s[1])
                    break
        elif mark is not None:
            title = _('Unsafes marked by')
        elif attr is not None:
            title = _('Unsafes where %(a_name)s is %(a_val)s') % {'a_name': attr.name.name, 'a_val': attr.value}
    else:
        title = _("All unknowns")
        if isinstance(problem, UnknownProblem):
            title = string_concat(_("Unknowns"), ': ', problem.name)
        elif problem == 0:
            title = string_concat(_("Unknowns without marks"))
        elif mark is not None:
            title = _('Unknowns marked by')
        elif attr is not None:
            title = _('Unknowns where %(a_name)s is %(a_val)s') % {'a_name': attr.name.name, 'a_val': attr.value}
    if mark is not None:
        title = string_concat(title, mark.identifier[:10])

    report_attrs_data = [request.user, report]
    if request.method == 'POST':
        if request.POST.get('view_type', None) == list_types[ltype]:
            report_attrs_data.append(request.POST.get('view', None))
            report_attrs_data.append(request.POST.get('view_id', None))

    table_data = reports.utils.ReportTable(
        *report_attrs_data, table_type=list_types[ltype],
        component_id=component_id, verdict=verdict, tag=tag, problem=problem, mark=mark, attr=attr
    )
    # If there is only one element in table, and first column of table is link, redirect to this link
    if len(table_data.table_data['values']) == 1 and isinstance(table_data.table_data['values'][0], list) \
            and len(table_data.table_data['values'][0]) > 0 and 'href' in table_data.table_data['values'][0][0] \
            and table_data.table_data['values'][0][0]['href']:
        return HttpResponseRedirect(table_data.table_data['values'][0][0]['href'])
    return render(
        request,
        'reports/report_list.html',
        {
            'report': report,
            'parents': reports.utils.get_parents(report),
            'TableData': table_data,
            'view_type': list_types[ltype],
            'title': title
        }
    )


@login_required
@unparallel_group(['UnsafeTag', 'SafeTag'])
def report_list_tag(request, report_id, ltype, tag_id):
    try:
        if ltype == 'unsafes':
            tag = UnsafeTag.objects.get(pk=int(tag_id))
        else:
            tag = SafeTag.objects.get(pk=int(tag_id))
    except ObjectDoesNotExist:
        return BridgeErrorResponse(_("The tag was not found"))
    return report_list(request, report_id, ltype, tag=tag.tag)


@login_required
def report_list_by_verdict(request, report_id, ltype, verdict):
    return report_list(request, report_id, ltype, verdict=verdict)


@login_required
@unparallel_group(['MarkSafe', 'MarkUnsafe', 'MarkUnknown'])
def report_list_by_mark(request, report_id, ltype, mark_id):
    tables = {
        'safes': MarkSafe,
        'unsafes': MarkUnsafe,
        'unknowns': MarkUnknown
    }
    try:
        return report_list(request, report_id, ltype, mark=tables[ltype].objects.get(pk=mark_id))
    except ObjectDoesNotExist:
        return BridgeErrorResponse(604)


@login_required
@unparallel_group(['Attr'])
def report_list_by_attr(request, report_id, ltype, attr_id):
    try:
        return report_list(request, report_id, ltype, attr=reports.models.Attr.objects.get(pk=attr_id))
    except ObjectDoesNotExist:
        return BridgeErrorResponse(_("The attribute was not found"))


@login_required
def report_unknowns(request, report_id, component_id):
    return report_list(request, report_id, 'unknowns', component_id=component_id)


@login_required
@unparallel_group(['UnknownProblem'])
def report_unknowns_by_problem(request, report_id, component_id, problem_id):
    problem_id = int(problem_id)
    if problem_id == 0:
        problem = 0
    else:
        try:
            problem = UnknownProblem.objects.get(pk=problem_id)
        except ObjectDoesNotExist:
            return BridgeErrorResponse(_("The problem was not found"))
    return report_list(request, report_id, 'unknowns', component_id=component_id, problem=problem)


@login_required
@unparallel_group(['ReportUnsafe'])
def report_unsafe(request, report_id):
    activate(request.user.extended.language)

    try:
        report = reports.models.ReportUnsafe.objects.get(pk=int(report_id))
    except ObjectDoesNotExist:
        return BridgeErrorResponse(504)

    if not JobAccess(request.user, report.root.job).can_view():
        return BridgeErrorResponse(400)

    main_file_content = None
    try:
        etv = GetETV(ArchiveFileContent(report, report.error_trace).content.decode('utf8'), request.user)
    except Exception as e:
        logger.exception(e, stack_info=True)
        etv = None
    try:
        tags = TagsInfo('unsafe', [])
    except Exception as e:
        logger.exception(e)
        return BridgeErrorResponse(500)

    try:
        return render(
            request, 'reports/report_unsafe.html',
            {
                'report': report,
                'parents': reports.utils.get_parents(report),
                'SelfAttrsData': reports.utils.report_attibutes(report),
                'MarkTable': ReportMarkTable(request.user, report),
                'etv': etv,
                'can_mark': MarkAccess(request.user, report=report).can_create(),
                'main_content': main_file_content,
                'include_assumptions': request.user.extended.assumptions,
                'markdata': MarkData('unsafe', report=report),
                'tags': tags,
                'include_jquery_ui': True
            }
        )
    except Exception as e:
        logger.exception("Error while visualizing error trace: %s" % e, stack_info=True)
        return BridgeErrorResponse(505)


@login_required
@unparallel_group(['ReportSafe'])
def report_safe(request, report_id):
    activate(request.user.extended.language)

    try:
        report = reports.models.ReportSafe.objects.get(pk=int(report_id))
    except ObjectDoesNotExist:
        return BridgeErrorResponse(504)

    if not JobAccess(request.user, report.root.job).can_view():
        return BridgeErrorResponse(400)

    main_file_content = None
    if report.archive and report.proof:
        try:
            main_file_content = ArchiveFileContent(report, report.proof).content.decode('utf8')
        except Exception as e:
            logger.exception("Couldn't extract proof from archive: %s" % e)
            return BridgeErrorResponse(500)
    try:
        tags = TagsInfo('safe', [])
    except Exception as e:
        logger.exception(e)
        return BridgeErrorResponse(500)

    try:
        return render(
            request, 'reports/report_safe.html',
            {
                'report': report,
                'parents': reports.utils.get_parents(report),
                'SelfAttrsData': reports.utils.report_attibutes(report),
                'MarkTable': ReportMarkTable(request.user, report),
                'can_mark': MarkAccess(request.user, report=report).can_create(),
                'main_content': main_file_content,
                'markdata': MarkData('safe', report=report),
                'tags': tags
            }
        )
    except Exception as e:
        logger.exception("Error while visualizing proof: %s" % e, stack_info=True)
        return BridgeErrorResponse(500)


@login_required
@unparallel_group(['ReportUnknown'])
def report_unknown(request, report_id):
    activate(request.user.extended.language)

    try:
        report = reports.models.ReportUnknown.objects.get(pk=int(report_id))
    except ObjectDoesNotExist:
        return BridgeErrorResponse(504)
    if not JobAccess(request.user, report.root.job).can_view():
        return BridgeErrorResponse(400)
    try:
        main_file_content = ArchiveFileContent(report, report.problem_description).content.decode('utf8')
    except Exception as e:
        logger.exception("Couldn't extract problem description from archive: %s" % e)
        return BridgeErrorResponse(500)

    try:
        return render(
            request, 'reports/report_unknown.html',
            {
                'report': report,
                'parents': reports.utils.get_parents(report),
                'SelfAttrsData': reports.utils.report_attibutes(report),
                'MarkTable': ReportMarkTable(request.user, report),
                'can_mark': MarkAccess(request.user, report=report).can_create(),
                'main_content': main_file_content,
                'markdata': MarkData('unknown', report=report)
            }
        )
    except Exception as e:
        logger.exception("Error while visualizing problem description: %s" % e, stack_info=True)
        return BridgeErrorResponse(500)


@login_required
@unparallel_group(['ReportUnsafe'])
def report_etv_full(request, report_id):
    activate(request.user.extended.language)

    try:
        report = reports.models.ReportUnsafe.objects.get(pk=int(report_id))
    except ObjectDoesNotExist:
        return BridgeErrorResponse(504)

    if not JobAccess(request.user, report.root.job).can_view():
        return BridgeErrorResponse(400)
    try:
        return render(request, 'reports/etv_fullscreen.html', {
            'report': report,
            'etv': GetETV(ArchiveFileContent(report, report.error_trace).content.decode('utf8'), request.user),
            'include_assumptions': request.user.extended.assumptions
        })
    except Exception as e:
        logger.exception(e, stack_info=True)
        return BridgeErrorResponse(505)


@unparallel_group([reports.models.ReportRoot, reports.models.AttrName, Task])
def upload_report(request):
    if not request.user.is_authenticated():
        return JsonResponse({'error': 'You are not signed in'})
    if request.method != 'POST':
        return JsonResponse({'error': 'Get request is not supported'})
    if 'job id' not in request.session:
        return JsonResponse({'error': 'The job id was not found in session'})
    try:
        job = Job.objects.get(pk=int(request.session['job id']))
    except ObjectDoesNotExist:
        return JsonResponse({'error': 'The job was not found'})
    except ValueError:
        return JsonResponse({'error': 'Unknown error'})
    if not JobAccess(request.user, job).klever_core_access():
        return JsonResponse({
            'error': "User '%s' don't have access to upload report for job '%s'" %
                     (request.user.username, job.identifier)
        })
    if job.status != JOB_STATUS[2][0]:
        return JsonResponse({'error': 'Reports can be uploaded only for processing jobs'})
    try:
        data = json.loads(request.POST.get('report', '{}'))
    except Exception as e:
        logger.exception("Json parsing error: %s" % e, stack_info=True)
        return JsonResponse({'error': 'Can not parse json data'})
    archive = None
    for f in request.FILES.getlist('file'):
        archive = f
    err = UploadReport(job, data, archive).error
    if err is not None:
        return JsonResponse({'error': err})
    return JsonResponse({})


@login_required
@unparallel_group(['ReportComponent'])
def get_component_log(request, report_id):
    report_id = int(report_id)
    try:
        report = reports.models.ReportComponent.objects.get(pk=int(report_id))
    except ObjectDoesNotExist:
        return BridgeErrorResponse(504)

    if not JobAccess(request.user, report.root.job).can_view():
        return BridgeErrorResponse(400)

    if report.log is None:
        return BridgeErrorResponse(_("The component doesn't have log"))
    logname = '%s-log.txt' % report.component.name

    try:
        content = ArchiveFileContent(report, report.log).content
    except Exception as e:
        logger.exception(e)
        return BridgeErrorResponse(500)

    response = StreamingHttpResponse(FileWrapper(BytesIO(content), 8192), content_type='text/plain')
    response['Content-Length'] = len(content)
    response['Content-Disposition'] = 'attachment; filename="%s"' % quote(logname)
    return response


@login_required
@unparallel_group(['ReportComponent'])
def get_log_content(request, report_id):
    report_id = int(report_id)
    try:
        report = reports.models.ReportComponent.objects.get(pk=int(report_id))
    except ObjectDoesNotExist:
        return BridgeErrorResponse(504)

    if not JobAccess(request.user, report.root.job).can_view():
        return BridgeErrorResponse(400)

    if report.log is None:
        return BridgeErrorResponse(_("The component doesn't have log"))

    try:
        content = ArchiveFileContent(report, report.log).content
    except Exception as e:
        logger.exception(str(e))
        return HttpResponse(str(_('Extraction of the component log from archive failed')))

    if len(content) > 10**5:
        return HttpResponse(str(_('The component log is huge and can not be showed but you can download it')))
    return HttpResponse(content.decode('utf8'))


@login_required
@unparallel_group(['ReportUnsafe'])
def get_source_code(request):
    activate(request.user.extended.language)
    if request.method != 'POST' or 'report_id' not in request.POST or 'file_name' not in request.POST:
        return JsonResponse({'error': str(UNKNOWN_ERROR)})

    try:
        result = GetSource(request.POST['report_id'], request.POST['file_name'])
    except BridgeException as e:
        return JsonResponse({'error': str(e)})
    except Exception as e:
        logger.exception(e)
        return JsonResponse({'error': str(UNKNOWN_ERROR)})
    filename = request.POST['file_name']
    if len(filename) > 50:
        filename = '.../' + filename[-50:].split('/', 1)[-1]
    return JsonResponse({
        'content': result.data, 'name': filename, 'fullname': request.POST['file_name']
    })


@login_required
@unparallel_group(['Job', 'ReportRoot', reports.models.CompareJobsInfo])
def fill_compare_cache(request):
    activate(request.user.extended.language)
    if request.method != 'POST':
        return JsonResponse({'error': str(UNKNOWN_ERROR)})
    try:
        j1 = Job.objects.get(pk=request.POST.get('job1', 0))
        j2 = Job.objects.get(pk=request.POST.get('job2', 0))
    except ObjectDoesNotExist:
        return JsonResponse({'error': _('One of the selected jobs was not found, please reload page')})
    if not can_compare(request.user, j1, j2):
        return JsonResponse({'error': _("You can't compare the selected jobs")})
    try:
        CompareTree(request.user, j1, j2)
    except Exception as e:
        logger.exception("Comparison of reports' trees failed: %s" % e)
        return JsonResponse({'error': str(UNKNOWN_ERROR)})
    return JsonResponse({})


@login_required
@unparallel_group([reports.models.CompareJobsInfo])
def jobs_comparison(request, job1_id, job2_id):
    activate(request.user.extended.language)
    try:
        job1 = Job.objects.get(pk=job1_id)
        job2 = Job.objects.get(pk=job2_id)
    except ObjectDoesNotExist:
        return BridgeErrorResponse(405)
    if not can_compare(request.user, job1, job2):
        return BridgeErrorResponse(507)
    try:
        tabledata = ComparisonTableData(request.user, job1, job2)
    except BridgeException as e:
        return BridgeErrorResponse(str(e))
    except Exception as e:
        logger.exception(e)
        return BridgeErrorResponse(500)
    return render(
        request, 'reports/comparison.html',
        {
            'job1': job1,
            'job2': job2,
            'tabledata': tabledata.data,
            'compare_info': tabledata.info,
            'attrs': tabledata.attrs
        }
    )


@login_required
@unparallel_group([reports.models.CompareJobsInfo])
def get_compare_jobs_data(request):
    activate(request.user.extended.language)
    if request.method != 'POST' or 'info_id' not in request.POST:
        return JsonResponse({'error': str(UNKNOWN_ERROR)})
    if all(x not in request.POST for x in ['verdict', 'attrs']):
        return JsonResponse({'error': str(UNKNOWN_ERROR)})
    try:
        result = ComparisonData(
            request.POST['info_id'], int(request.POST.get('page_num', 1)),
            True if 'hide_attrs' in request.POST else False,
            True if 'hide_components' in request.POST else False,
            request.POST.get('verdict', None), request.POST.get('attrs', None)
        )
    except BridgeException as e:
        return JsonResponse({'error': str(e)})
    except Exception as e:
        logger.exception(e)
        return JsonResponse({'error': str(UNKNOWN_ERROR)})
    v1 = result.v1
    v2 = result.v2
    for v in COMPARE_VERDICT:
        if result.v1 == v[0]:
            v1 = v[1]
        if result.v2 == v[0]:
            v2 = v[1]
    return render(
        request, 'reports/comparisonData.html',
        {
            'verdict1': v1,
            'verdict2': v2,
            'job1': result.info.root1.job,
            'job2': result.info.root2.job,
            'data': result.data,
            'pages': result.pages,
            'verdict': request.POST.get('verdict', None),
            'attrs': request.POST.get('attrs', None)
        }
    )


@login_required
@unparallel_group(['ReportComponent'])
def download_report_files(request, report_id):
    try:
        report = reports.models.ReportComponent.objects.get(pk=int(report_id))
    except ObjectDoesNotExist:
        return BridgeErrorResponse(504)
    if not report.archive:
        return BridgeErrorResponse(_("The report doesn't have files"))

    response = StreamingHttpResponse(FileWrapper(report.archive.file, 8192), content_type='application/zip')
    response['Content-Length'] = len(report.archive.file)
    response['Content-Disposition'] = 'attachment; filename="%s files.zip"' % report.component.name
    return response


@login_required
@unparallel_group(['ReportUnsafe'])
def download_error_trace(request, report_id):
    if request.method != 'GET':
        return BridgeErrorResponse(301)
    try:
        report = reports.models.ReportUnsafe.objects.get(id=report_id)
    except ObjectDoesNotExist:
        return BridgeErrorResponse(504)
    content = ArchiveFileContent(report, report.error_trace).content
    response = StreamingHttpResponse(FileWrapper(BytesIO(content), 8192), content_type='application/json')
    response['Content-Length'] = len(content)
    response['Content-Disposition'] = 'attachment; filename="error-trace.json"'
    return response


@login_required
@unparallel_group([reports.models.Report])
def clear_verification_files(request):
    if request.method != 'POST' or 'job_id' not in request.POST:
        return JsonResponse({'error': str(UNKNOWN_ERROR)})
    try:
        job = Job.objects.get(id=request.POST['job_id'])
    except ObjectDoesNotExist:
        return JsonResponse({'error': _("The job was not found or wasn't decided")})
    if not JobAccess(request.user, job).can_clear_verifications():
        return JsonResponse({'error': _("You can't remove verification files of this job")})
    try:
        reports.utils.remove_verification_files(job)
    except Exception as e:
        logger.exception(e)
        return JsonResponse({'error': str(UNKNOWN_ERROR)})
    return JsonResponse({})
