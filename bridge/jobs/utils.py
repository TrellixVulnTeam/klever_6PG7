import os
import re
import json
import hashlib
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.template import Template, Context
from django.utils.translation import ugettext_lazy as _, string_concat
from django.utils.timezone import now
from bridge.settings import KLEVER_CORE_PARALLELISM_PACKS, KLEVER_CORE_LOG_FORMATTERS, LOGGING_LEVELS,\
    DEF_KLEVER_CORE_MODE, DEF_KLEVER_CORE_MODES
from bridge.utils import logger
from bridge.vars import JOB_STATUS, AVTG_PRIORITY, KLEVER_CORE_PARALLELISM, KLEVER_CORE_FORMATTERS,\
    USER_ROLES, JOB_ROLES, SCHEDULER_TYPE, PRIORITY, START_JOB_DEFAULT_MODES, SCHEDULER_STATUS
from jobs.models import Job, JobHistory, FileSystem, File, UserRole
from users.notifications import Notify
from reports.models import CompareJobsInfo, ReportComponent
from service.models import SchedulerUser, Scheduler


READABLE = ['txt', 'json', 'xml', 'c', 'aspect', 'i', 'h', 'tmpl']

# List of available types of 'safe' column class.
SAFES = [
    'missed_bug',
    'incorrect',
    'unknown',
    'inconclusive',
    'unassociated',
    'total'
]

# List of available types of 'unsafe' column class.
UNSAFES = [
    'bug',
    'target_bug',
    'false_positive',
    'unknown',
    'inconclusive',
    'unassociated',
    'total'
]

# Dictionary of titles of static columns
TITLES = {
    'name': _('Title'),
    'author': _('Author'),
    'date': _('Last change'),
    'status': _('Decision status'),
    'safe': _('Safes'),
    'safe:missed_bug': _('Missed target bugs'),
    'safe:incorrect': _('Incorrect proof'),
    'safe:unknown': _('Unknown'),
    'safe:inconclusive': _('Incompatible marks'),
    'safe:unassociated': _('Without marks'),
    'safe:total': _('Total'),
    'unsafe': _('Unsafes'),
    'unsafe:bug': _('Bugs'),
    'unsafe:target_bug': _('Target bugs'),
    'unsafe:false_positive': _('False positives'),
    'unsafe:unknown': _('Unknown'),
    'unsafe:inconclusive': _('Incompatible marks'),
    'unsafe:unassociated': _('Without marks'),
    'unsafe:total': _('Total'),
    'problem': _('Unknowns'),
    'problem:total': _('Total'),
    'resource': _('Consumed resources'),
    'resource:total': _('Total'),
    'tag': _('Tags'),
    'tag:safe': _('Safes'),
    'tag:unsafe': _('Unsafes'),
    'identifier': _('Identifier'),
    'format': _('Format'),
    'version': _('Version'),
    'type': _('Class'),
    'parent_id': string_concat(_('Parent'), '/', _('Identifier')),
    'role': _('Your role'),
    'priority': _('Priority'),
    'start_date': _('Decision start date'),
    'finish_date': _('Decision finish date'),
    'solution_wall_time': _('Decision wall time'),
    'operator': _('Operator'),
    'tasks_pending': _('Pending tasks'),
    'tasks_processing': _('Processing tasks'),
    'tasks_finished': _('Finished tasks'),
    'tasks_error': _('Error tasks'),
    'tasks_cancelled': _('Cancelled tasks'),
    'tasks_total': _('Total tasks'),
    'progress': _('Progress of job decision'),
    'solutions': _('Number of task decisions')
}


class JobAccess(object):

    def __init__(self, user, job=None):
        self.job = job
        self.__is_author = False
        self.__job_role = None
        self.__user_role = user.extended.role
        self.__is_manager = (self.__user_role == USER_ROLES[2][0])
        self.__is_expert = (self.__user_role == USER_ROLES[3][0])
        self.__is_service = (self.__user_role == USER_ROLES[4][0])
        self.__is_operator = False
        try:
            if self.job is not None:
                self.__is_operator = (user == self.job.reportroot.user)
        except ObjectDoesNotExist:
            pass
        self.__get_prop(user)

    def klever_core_access(self):
        if self.job is None:
            return False
        return self.__is_manager or self.__is_service

    def can_decide(self):
        if self.job is None or self.job.status in [JOB_STATUS[1][0], JOB_STATUS[2][0]]:
            return False
        return self.__is_manager or self.__is_author or self.__job_role in [JOB_ROLES[3][0], JOB_ROLES[4][0]]

    def can_view(self):
        if self.job is None:
            return False
        return self.__is_manager or self.__is_author or self.__job_role != JOB_ROLES[0][0] or self.__is_expert

    def can_create(self):
        return self.__user_role not in [USER_ROLES[0][0], USER_ROLES[4][0]]

    def can_edit(self):
        if self.job is None:
            return False
        return self.job.status not in [JOB_STATUS[1][0], JOB_STATUS[2][0]] and (self.__is_author or self.__is_manager)

    def can_stop(self):
        if self.job is None:
            return False
        if self.job.status in [JOB_STATUS[1][0], JOB_STATUS[2][0]] \
                and (self.__is_operator or self.__is_manager):
            return True
        return False

    def can_delete(self):
        if self.job is None:
            return False
        if len(self.job.children.all()) > 0:
            return False
        if self.__is_manager and self.job.status == JOB_STATUS[3]:
            return True
        if self.job.status in [js[0] for js in JOB_STATUS[1:2]]:
            return False
        return self.__is_author or self.__is_manager

    def can_download(self):
        return not (self.job is None or self.job.status in [JOB_STATUS[2][0], JOB_STATUS[5][0], JOB_STATUS[6][0]])

    def __get_prop(self, user):
        if self.job is not None:
            try:
                first_version = self.job.versions.get(version=1)
                last_version = self.job.versions.get(
                    version=self.job.version)
            except ObjectDoesNotExist:
                return
            self.__is_author = (first_version.change_author == user)
            last_v_role = last_version.userrole_set.filter(user=user)
            if len(last_v_role) > 0:
                self.__job_role = last_v_role[0].role
            else:
                self.__job_role = last_version.global_role


class FileData(object):

    def __init__(self, job):
        self.filedata = []
        self.__get_filedata(job)
        self.__order_by_type()
        self.__order_by_lvl()

    def __get_filedata(self, job):
        for f in job.filesystem_set.all().order_by('name'):
            file_info = {
                'title': f.name,
                'id': f.pk,
                'parent': None,
                'hash_sum': None,
                'type': 0
            }
            if f.parent:
                file_info['parent'] = f.parent_id
            if f.file:
                file_info['type'] = 1
                file_info['hash_sum'] = f.file.hash_sum
            self.filedata.append(file_info)

    def __order_by_type(self):
        newfilesdata = []
        for fd in self.filedata:
            if fd['type'] == 0:
                newfilesdata.append(fd)
        for fd in self.filedata:
            if fd['type'] == 1:
                newfilesdata.append(fd)
        self.filedata = newfilesdata

    def __order_by_lvl(self):
        ordered_data = []
        first_lvl = []
        other_data = []
        for fd in self.filedata:
            if fd['parent'] is None:
                first_lvl.append(fd)
            else:
                other_data.append(fd)

        def __get_all_children(file_info):
            children = []
            if file_info['type'] == 1:
                return children
            for fi in other_data:
                if fi['parent'] == file_info['id']:
                    children.append(fi)
                    children.extend(__get_all_children(fi))
            return children

        for fd in first_lvl:
            ordered_data.append(fd)
            ordered_data.extend(__get_all_children(fd))
        self.filedata = ordered_data


class SaveFileData(object):

    def __init__(self, filedata, job):
        self.filedata = filedata
        self.job = job
        self.filedata_by_lvl = []
        self.filedata_hash = {}
        self.err_message = self.__validate()
        if self.err_message is None:
            self.err_message = self.__save_file_data()

    def __save_file_data(self):
        for lvl in self.filedata_by_lvl:
            for lvl_elem in lvl:
                fs_elem = FileSystem()
                fs_elem.job = self.job
                if lvl_elem['parent']:
                    parent_pk = self.filedata_hash[lvl_elem['parent']].get(
                        'pk', None
                    )
                    if parent_pk is None:
                        return _("Saving folder failed")
                    try:
                        parent = FileSystem.objects.get(pk=parent_pk, file=None)
                    except ObjectDoesNotExist:
                        return _("Saving folder failed")
                    fs_elem.parent = parent
                if lvl_elem['type'] == '1':
                    try:
                        fs_elem.file = File.objects.get(
                            hash_sum=lvl_elem['hash_sum']
                        )
                    except ObjectDoesNotExist:
                        return _("The file was not uploaded")
                if not all(ord(c) < 128 for c in lvl_elem['title']):
                    t_size = len(lvl_elem['title'])
                    if t_size > 30:
                        lvl_elem['title'] = lvl_elem['title'][(t_size - 30):]
                fs_elem.name = lvl_elem['title']
                fs_elem.save()
                self.filedata_hash[lvl_elem['id']]['pk'] = fs_elem.pk
        return None

    def __validate(self):
        num_of_elements = 0
        element_of_lvl = []
        cnt = 0
        while num_of_elements < len(self.filedata):
            cnt += 1
            if cnt > 1000:
                return _("Unknown error")
            num_of_elements += len(element_of_lvl)
            element_of_lvl = self.__get_lower_level(element_of_lvl)
            if len(element_of_lvl):
                self.filedata_by_lvl.append(element_of_lvl)
        for lvl in self.filedata_by_lvl:
            names_of_lvl = []
            names_with_parents = []
            for fd in lvl:
                self.filedata_hash[fd['id']] = fd
                if len(fd['title']) == 0:
                    return _("You can't specify an empty name")
                if not all(ord(c) < 128 for c in fd['title']):
                    title_size = len(fd['title'])
                    if title_size > 30:
                        fd['title'] = fd['title'][(title_size - 30):]
                if fd['type'] == '1' and fd['hash_sum'] is None:
                    return _("The file was not uploaded")
                if [fd['title'], fd['parent']] in names_with_parents:
                    return _("You can't use the same names in one folder")
                names_of_lvl.append(fd['title'])
                names_with_parents.append([fd['title'], fd['parent']])
        return None

    def __get_lower_level(self, data):
        new_level = []
        if len(data):
            for d in data:
                for fd in self.filedata:
                    if fd['parent'] == d['id']:
                        if fd not in new_level:
                            new_level.append(fd)
        else:
            for fd in self.filedata:
                if fd['parent'] is None:
                    new_level.append(fd)
        return new_level


def convert_time(val, acc):
    def final_value(time, postfix):
        fpart_len = len(str(round(time)))
        if fpart_len > int(acc):
            tmp_div = 10**(fpart_len - int(acc))
            rounded_value = round(time/tmp_div) * tmp_div
        elif fpart_len == int(acc):
            rounded_value = round(time)
        else:
            rounded_value = round(time, int(acc) - fpart_len)
        return Template('{% load l10n %}{{ val }} {{ postfix }}').render(Context({
            'val': rounded_value, 'postfix': postfix
        }))

    new_time = int(val)
    try_div = new_time / 1000
    if try_div < 1:
        return final_value(new_time, _('ms'))
    new_time = try_div
    try_div = new_time / 60
    if try_div < 1:
        return final_value(new_time, _('s'))
    new_time = try_div
    try_div = new_time / 60
    if try_div < 1:
        return final_value(new_time, _('min'))
    return final_value(try_div, _('h'))


def convert_memory(val, acc):
    def final_value(memory, postfix):
        fpart_len = len(str(round(memory)))
        if fpart_len > int(acc):
            tmp_div = 10 ** (fpart_len - int(acc))
            rounded_value = round(memory / tmp_div) * tmp_div
        elif fpart_len == int(acc):
            rounded_value = round(memory)
        else:
            rounded_value = round(memory, int(acc) - fpart_len)
        return Template('{% load l10n %}{{ val }} {{ postfix }}').render(Context({
            'val': rounded_value, 'postfix': postfix
        }))

    new_mem = int(val)
    try_div = new_mem / 10**3
    if try_div < 1:
        return final_value(new_mem, _('B'))
    new_mem = try_div
    try_div = new_mem / 10**3
    if try_div < 1:
        return final_value(new_mem, _('KB'))
    new_mem = try_div
    try_div = new_mem / 10**3
    if try_div < 1:
        return final_value(new_mem, _('MB'))
    return final_value(try_div, _('GB'))


def role_info(job, user):
    roles_data = {'global': job.global_role}

    users = []
    user_roles_data = []
    users_roles = job.userrole_set.filter(~Q(user=user))
    job_author = job.job.versions.get(version=1).change_author

    for ur in users_roles:
        title = ur.user.extended.last_name + ' ' + ur.user.extended.first_name
        u_id = ur.user_id
        user_roles_data.append({
            'user': {'id': u_id, 'name': title},
            'role': {'val': ur.role, 'title': ur.get_role_display()}
        })
        users.append(u_id)

    roles_data['user_roles'] = user_roles_data

    available_users = []
    for u in User.objects.filter(~Q(pk__in=users) & ~Q(pk=user.pk)):
        if u != job_author:
            available_users.append({
                'id': u.pk,
                'name': u.extended.last_name + ' ' + u.extended.first_name
            })
    roles_data['available_users'] = available_users
    return roles_data


def create_version(job, kwargs):
    new_version = JobHistory()
    new_version.job = job
    new_version.parent = job.parent
    new_version.version = job.version
    new_version.change_author = job.change_author
    new_version.change_date = job.change_date
    new_version.name = job.name
    if 'comment' in kwargs:
        new_version.comment = kwargs['comment']
    if 'global_role' in kwargs and \
            kwargs['global_role'] in list(x[0] for x in JOB_ROLES):
        new_version.global_role = kwargs['global_role']
    if 'description' in kwargs:
        new_version.description = kwargs['description']
    new_version.save()
    if 'user_roles' in kwargs:
        for ur in kwargs['user_roles']:
            try:
                ur_user = User.objects.get(pk=int(ur['user']))
            except ObjectDoesNotExist:
                continue
            new_ur = UserRole()
            new_ur.job = new_version
            new_ur.user = ur_user
            new_ur.role = ur['role']
            new_ur.save()
    return new_version


def create_job(kwargs):
    newjob = Job()
    if 'name' not in kwargs or len(kwargs['name']) == 0:
        return _("The job title is required")
    if 'author' not in kwargs or not isinstance(kwargs['author'], User):
        return _("The job author is required")
    newjob.name = kwargs['name']
    newjob.change_author = kwargs['author']
    if 'parent' in kwargs:
        newjob.parent = kwargs['parent']
        newjob.type = kwargs['parent'].type
    elif 'type' in kwargs:
        newjob.type = kwargs['type']
    else:
        return _("The parent or the job class is required")
    if 'pk' in kwargs:
        try:
            Job.objects.get(pk=int(kwargs['pk']))
        except ObjectDoesNotExist:
            newjob.pk = int(kwargs['pk'])

    time_encoded = now().strftime("%Y%m%d%H%M%S%f%z").encode('utf-8')
    newjob.identifier = hashlib.md5(time_encoded).hexdigest()
    newjob.save()

    new_version = create_version(newjob, kwargs)

    if 'filedata' in kwargs:
        db_fdata = SaveFileData(kwargs['filedata'], new_version)
        if db_fdata.err_message is not None:
            newjob.delete()
            return db_fdata.err_message
    if 'absolute_url' in kwargs:
        newjob_url = reverse('jobs:job', args=[newjob.pk])
        try:
            Notify(newjob, 0, {
                'absurl': kwargs['absolute_url'] + newjob_url
            })
        except Exception as e:
            logger.exception("Can't notify users: %s" % e)
    else:
        try:
            Notify(newjob, 0)
        except Exception as e:
            logger.exception("Can't notify users: %s" % e)
    return newjob


def update_job(kwargs):
    if 'job' not in kwargs or not isinstance(kwargs['job'], Job):
        return _("Unknown error")
    if 'author' not in kwargs or not isinstance(kwargs['author'], User):
        return _("Change author is required")
    if 'comment' in kwargs:
        if len(kwargs['comment']) == 0:
            return _("Change comment is required")
    else:
        kwargs['comment'] = ''
    if 'parent' in kwargs:
        kwargs['job'].parent = kwargs['parent']
    if 'name' in kwargs and len(kwargs['name']) > 0:
        kwargs['job'].name = kwargs['name']
    kwargs['job'].change_author = kwargs['author']
    kwargs['job'].version += 1
    kwargs['job'].save()

    newversion = create_version(kwargs['job'], kwargs)

    if 'filedata' in kwargs:
        db_fdata = SaveFileData(kwargs['filedata'], newversion)
        if db_fdata.err_message is not None:
            newversion.delete()
            kwargs['job'].version -= 1
            kwargs['job'].save()
            return db_fdata.err_message
    if 'absolute_url' in kwargs:
        try:
            Notify(kwargs['job'], 1, {'absurl': kwargs['absolute_url']})
        except Exception as e:
            logger.exception("Can't notify users: %s" % e)
    else:
        try:
            Notify(kwargs['job'], 1)
        except Exception as e:
            logger.exception("Can't notify users: %s" % e)
    return kwargs['job']


def remove_jobs_by_id(user, job_ids):
    jobs = []
    for job_id in job_ids:
        try:
            jobs.append(Job.objects.get(pk=job_id))
        except ObjectDoesNotExist:
            return 404
    for job in jobs:
        if not JobAccess(user, job).can_delete():
            return 400
    for job in jobs:
        try:
            Notify(job, 2)
        except Exception as e:
            logger.exception("Can't notify users: %s" % e)
        job.delete()
    return 0


def delete_versions(job, versions):
    access_versions = []
    for v in versions:
        v = int(v)
        if v != 1 and v != job.version:
            access_versions.append(v)
    checked_versions = job.versions.filter(version__in=access_versions)
    num_of_deleted = len(checked_versions)
    checked_versions.delete()
    return num_of_deleted


def check_new_parent(job, parent):
    if job.type != parent.type:
        return False
    if job.parent == parent:
        return True
    while parent is not None:
        if parent == job:
            return False
        parent = parent.parent
    return True


def get_resource_data(user, resource):
    if user.extended.data_format == 'hum':
        wall = convert_time(resource.wall_time, user.extended.accuracy)
        cpu = convert_time(resource.cpu_time, user.extended.accuracy)
        mem = convert_memory(resource.memory, user.extended.accuracy)
    else:
        wall = "%s %s" % (resource.wall_time, _('ms'))
        cpu = "%s %s" % (resource.cpu_time, _('ms'))
        mem = "%s %s" % (resource.memory, _('B'))
    return [wall, cpu, mem]


def get_user_time(user, milliseconds):
    if user.extended.data_format == 'hum':
        converted = convert_time(int(milliseconds), user.extended.accuracy)
    else:
        converted = "%s %s" % (int(milliseconds), _('ms'))
    return converted


class CompareFileSet(object):
    def __init__(self, job1, job2):
        self.j1 = job1
        self.j2 = job2
        self.data = {
            'same': [],
            'diff': [],
            'unmatched1': [],
            'unmatched2': []
        }
        self.__get_comparison()

    def __get_comparison(self):

        def get_files(job):
            files = []
            last_v = job.versions.order_by('-version')[0]
            for f in last_v.filesystem_set.all():
                if f.file is not None:
                    parent = f.parent
                    f_name = f.name
                    while parent is not None:
                        f_name = os.path.join(parent.name, f_name)
                        parent = parent.parent
                    files.append([f_name, f.file.hash_sum])
            return files

        files1 = get_files(self.j1)
        files2 = get_files(self.j2)
        for f1 in files1:
            if f1[0] not in list(x[0] for x in files2):
                ext = os.path.splitext(f1[0])[1]
                if len(ext) > 0 and ext[1:] in READABLE:
                    self.data['unmatched1'].insert(0, [f1[0], f1[1]])
                else:
                    self.data['unmatched1'].append([f1[0]])
            else:
                for f2 in files2:
                    if f2[0] == f1[0]:
                        ext = os.path.splitext(f1[0])[1]
                        if f2[1] == f1[1]:
                            if len(ext) > 0 and ext[1:] in READABLE:
                                self.data['same'].insert(0, [f1[0], f1[1]])
                            else:
                                self.data['same'].append([f1[0]])
                        else:
                            if len(ext) > 0 and ext[1:] in READABLE:
                                self.data['diff'].insert(0, [f1[0], f1[1], f2[1]])
                            else:
                                self.data['diff'].append([f1[0]])
                        break
        for f2 in files2:
            if f2[0] not in list(x[0] for x in files1):
                ext = os.path.splitext(f2[0])[1]
                if len(ext) > 0 and ext[1:] in READABLE:
                    self.data['unmatched2'].insert(0, [f2[0], f2[1]])
                else:
                    self.data['unmatched2'].append([f2[0]])


class GetFilesComparison(object):
    def __init__(self, user, job1, job2):
        self.user = user
        self.job1 = job1
        self.job2 = job2
        self.data = self.__get_info()

    def __get_info(self):
        try:
            info = CompareJobsInfo.objects.get(user=self.user, root1=self.job1.reportroot, root2=self.job2.reportroot)
        except ObjectDoesNotExist:
            self.error = _('The comparison cache was not found')
            return
        return json.loads(info.files_diff)


def change_job_status(job, status):
    if not isinstance(job, Job) or status not in list(x[0] for x in JOB_STATUS):
        return
    if status in [JOB_STATUS[3], JOB_STATUS[4]]:
        for comp in ReportComponent.objects.filter(root=job.reportroot, finish_date=None):
            comp.finish_date = now()
            comp.save()
    job.status = status
    job.save()
    try:
        run_data = job.runhistory_set.latest('date')
        run_data.status = status
        run_data.save()
    except ObjectDoesNotExist:
        pass


def get_default_configurations():
    configurations = []
    for conf in DEF_KLEVER_CORE_MODES:
        mode = next(iter(conf))
        configurations.append([
            mode,
            START_JOB_DEFAULT_MODES[mode] if mode in START_JOB_DEFAULT_MODES else mode
        ])
    return configurations


class GetConfiguration(object):
    def __init__(self, conf_name=None, file_conf=None, user_conf=None):
        self.configuration = None
        if conf_name is not None:
            self.__get_default_conf(conf_name)
        elif file_conf is not None:
            self.__get_file_conf(file_conf)
        elif user_conf is not None:
            self.__get_user_conf(user_conf)
        if not self.__check_conf():
            self.configuration = None

    def __get_default_conf(self, name):
        if name is None:
            name = DEF_KLEVER_CORE_MODE
        conf_template = None
        for conf in DEF_KLEVER_CORE_MODES:
            mode = next(iter(conf))
            if mode == name:
                conf_template = conf[mode]
        if conf_template is None:
            return
        try:
            self.configuration = [
                list(conf_template[0]),
                list(KLEVER_CORE_PARALLELISM_PACKS[conf_template[1]]),
                list(conf_template[2]),
                [
                    conf_template[3][0],
                    KLEVER_CORE_LOG_FORMATTERS[conf_template[3][1]],
                    conf_template[3][2],
                    KLEVER_CORE_LOG_FORMATTERS[conf_template[3][3]],
                ],
                list(conf_template[4:])
            ]
        except Exception as e:
            logger.exception("Wrong default configuration format: %s" % e, stack_info=True)

    def __get_file_conf(self, filedata):
        scheduler = None
        for sch in SCHEDULER_TYPE:
            if sch[1] == filedata['task scheduler']:
                scheduler = sch[0]
        if scheduler is None:
            logger.error('Scheduler %s is not supported' % filedata['task scheduler'], stack_info=True)
            return

        cpu_time = filedata['resource limits']['CPU time']
        if isinstance(cpu_time, int):
            cpu_time = float("%0.3f" % (filedata['resource limits']['CPU time'] / (6 * 10**4)))
        wall_time = filedata['resource limits']['wall time']
        if isinstance(wall_time, int):
            wall_time = float("%0.3f" % (filedata['resource limits']['wall time'] / (6 * 10**4)))

        try:
            formatters = {}
            for f in filedata['logging']['formatters']:
                formatters[f['name']] = f['value']
            loggers = {}
            for l in filedata['logging']['loggers']:
                loggers[l['name']] = {
                    'formatter': formatters[l['formatter']],
                    'level': l['level']
                }
            logging = [
                loggers['console']['level'],
                loggers['console']['formatter'],
                loggers['file']['level'],
                loggers['file']['formatter']
            ]
        except Exception as e:
            logger.exception("Wrong logging format: %s" % e)
            return

        try:
            self.configuration = [
                [filedata['priority'], scheduler, filedata['abstract task generation priority']],
                [filedata['parallelism']['Build'], filedata['parallelism']['Tasks generation']],
                [
                    filedata['resource limits']['memory size'] / 10**9,
                    filedata['resource limits']['number of CPU cores'],
                    filedata['resource limits']['disk memory size'] / 10**9,
                    filedata['resource limits']['CPU model'],
                    cpu_time, wall_time
                ],
                logging,
                [
                    filedata['keep intermediate files'],
                    filedata['upload input files of static verifiers'],
                    filedata['upload other intermediate files'],
                    filedata['allow local source directories use'],
                    filedata['ignore another instances']
                ]
            ]
        except Exception as e:
            logger.exception("Wrong core configuration format: %s" % e, stack_info=True)

    def __get_user_conf(self, conf):
        def int_or_float(val):
            m = re.match('^\s*(\d+),(\d+)\s*$', val)
            if m is not None:
                val = '%s.%s' % (m.group(1), m.group(2))
            try:
                return int(val)
            except ValueError:
                return float(val)

        try:
            conf[1][0] = int_or_float(conf[1][0])
            conf[1][1] = int_or_float(conf[1][1])
            if len(conf[2][3]) == 0:
                conf[2][3] = None
            conf[2][0] = float(conf[2][0])
            conf[2][1] = int(conf[2][1])
            conf[2][2] = float(conf[2][2])
            if conf[2][4] is not None:
                conf[2][4] = float(conf[2][4])
            if conf[2][5] is not None:
                conf[2][5] = float(conf[2][5])
        except Exception as e:
            logger.exception("Wrong user configuration format: %s" % e, stack_info=True)
            return
        self.configuration = conf

    def __check_conf(self):
        if not isinstance(self.configuration, list) or len(self.configuration) != 5:
            return False
        if not isinstance(self.configuration[0], list) or len(self.configuration[0]) != 3:
            return False
        if not isinstance(self.configuration[1], list) or len(self.configuration[1]) != 2:
            return False
        if not isinstance(self.configuration[2], list) or len(self.configuration[2]) != 6:
            return False
        if not isinstance(self.configuration[3], list) or len(self.configuration[3]) != 4:
            return False
        if not isinstance(self.configuration[4], list) or len(self.configuration[4]) != 5:
            return False
        if self.configuration[0][0] not in list(x[0] for x in PRIORITY):
            return False
        if self.configuration[0][1] not in list(x[0] for x in SCHEDULER_TYPE):
            return False
        if self.configuration[0][2] not in list(x[0] for x in AVTG_PRIORITY):
            return False
        if not isinstance(self.configuration[1][0], (float, int)):
            return False
        if not isinstance(self.configuration[1][1], (float, int)):
            return False
        if not isinstance(self.configuration[2][0], (float, int)):
            return False
        if not isinstance(self.configuration[2][1], int):
            return False
        if not isinstance(self.configuration[2][2], (float, int)):
            return False
        if not isinstance(self.configuration[2][3], str) and self.configuration[2][3] is not None:
            return False
        if not isinstance(self.configuration[2][4], (float, int)) and self.configuration[2][4] is not None:
            return False
        if not isinstance(self.configuration[2][5], (float, int)) and self.configuration[2][5] is not None:
            return False
        if self.configuration[3][0] not in LOGGING_LEVELS:
            return False
        if self.configuration[3][2] not in LOGGING_LEVELS:
            return False
        if not isinstance(self.configuration[3][1], str) or not isinstance(self.configuration[3][3], str):
            return False
        if any(not isinstance(x, bool) for x in self.configuration[4]):
            return False
        return True


class StartDecisionData(object):
    def __init__(self, user, data):
        self.error = None
        self.default = data

        self.job_sch_err = None
        self.schedulers = self.__get_schedulers()
        if self.error is not None:
            return

        self.priorities = list(reversed(PRIORITY))
        self.logging_levels = LOGGING_LEVELS
        self.parallelism = KLEVER_CORE_PARALLELISM
        self.formatters = KLEVER_CORE_FORMATTERS
        self.avtg_priorities = AVTG_PRIORITY

        self.need_auth = False
        try:
            SchedulerUser.objects.get(user=user)
        except ObjectDoesNotExist:
            self.need_auth = True

    def __get_schedulers(self):
        schedulers = []
        try:
            klever_sch = Scheduler.objects.get(type=SCHEDULER_TYPE[0][0])
        except ObjectDoesNotExist:
            self.error = 'Unknown error'
            return []
        try:
            cloud_sch = Scheduler.objects.get(type=SCHEDULER_TYPE[1][0])
        except ObjectDoesNotExist:
            self.error = 'Unknown error'
            return []
        if klever_sch.status == SCHEDULER_STATUS[1][0]:
            self.job_sch_err = _("The Klever scheduler is ailing")
        elif klever_sch.status == SCHEDULER_STATUS[2][0]:
            self.error = _("The Klever scheduler is disconnected")
            return []
        schedulers.append([
            klever_sch.type,
            string_concat(klever_sch.get_type_display(), ' (', klever_sch.get_status_display(), ')')
        ])
        if cloud_sch.status != SCHEDULER_STATUS[2][0]:
            schedulers.append([
                cloud_sch.type,
                string_concat(cloud_sch.get_type_display(), ' (', cloud_sch.get_status_display(), ')')
            ])
        return schedulers
