# -*- coding: utf-8 -*-
#########################################################
# python
import os
import traceback
import logging
import re
import threading
import json
import time
import requests
from datetime import datetime

from flask import Blueprint, request, Response, send_file, render_template, redirect, jsonify 
from flask_socketio import SocketIO, emit, send
from flask_login import login_user, logout_user, current_user, login_required

# sjva 공용
from framework import app, db, socketio, path_data, path_app_root, py_queue
from framework.util import Util, AlchemyEncoder
from tool_base import ToolBaseNotify

# 패키지
from .plugin import package_name, logger
from .model import ModelSetting, ModelDownloaderItem

# pikpak
try:
    from pikpakapi import PikPakApi
    from pikpakapi.PikpakException import PikpakException, PikpakAccessTokenExpireException
except ImportError:
    os.system("{} install pikpakapi".format(app.config['config']['pip']))
    from pikpakapi import PikPakApi
    from pikpakapi.PikpakException import PikpakException, PikpakAccessTokenExpireException


#########################################################

class LogicPikPak(object):
    client = None
    download_folder_id = None
    upload_folder_id = None
    prev_tasks = None
    torrent_info_installed = False
    current_tasks = None

    MoveThread = None
    MoveQueue = None

    RemoveThread = None
    RemoveQueue = None
    
    CurrentQuota = None

    @staticmethod
    def process_ajax(sub, req):
        try:
            if sub == 'login':
                username = req.form['pikpak_username']
                password = req.form['pikpak_password']
                ret = LogicPikPak.login(username, password)
                return jsonify(ret)
            elif sub == 'get_status':
                return jsonify(LogicPikPak.get_status())
            elif sub == 'remove':
                data = LogicPikPak.remove(request.form['task_id'])
                return jsonify(data)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def login(username=None, password=None):
        try:
            if not username: username = ModelSetting.get('pikpak_username')
            if not password: password = ModelSetting.get('pikpak_password')
            ret = {}
            LogicPikPak.client = PikPakApi(username=username, password=password)
            while True:
                try:
                    LogicPikPak.client.login()
                    break
                except Exception as e:
                    logger.warning('Exception:%s, retry login()', e)
                    time.sleep(0.5)

            c = LogicPikPak.client
            logger.debug(f'[로그인성공] {c.username},{c.user_id},access_token({c.access_token}),refresh_token({c.refresh_token})')
            ret['ret'] = 'success'
            tasks = LogicPikPak.get_status()
            ret['current'] = len(tasks)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret['ret'] = 'fail'
            ret['log'] = str(e)
        finally:
            return ret
    
    @staticmethod
    def path_to_id(path, create=False):
        try:
            ret = {}
            client = LogicPikPak.client
            size = 100

            paths = path.split('/')
            paths = [p.strip() for p in paths if len(p) > 0]
            path_ids = []
            count = 0
            next_page_token = None
            parent_id = None

            while count < len(paths):
                data = client.file_list(parent_id=parent_id, next_page_token=next_page_token)
                file_id = ""
                for f in data.get("files", []):
                    if f.get("name") == paths[count]:
                        file_id = f.get("id")
                        break

                if file_id != "":
                    path_ids.append({"id":file_id, "name":paths[count]})
                    count = count + 1
                    parent_id = file_id
                elif data.get("next_page_token"):
                    next_page_doken = data.get("next_page_token")
                elif create:
                    data = client.create_folder(name=paths[count], parent_id=parent_id)
                    file_id = data.get("file").get("id")
                    path_ids.append({"id":file_id, "name":paths[count]})
                    count = count + 1
                    parent_id = file_id
                else:
                    break

            ret['ret'] = 'success'
            ret['data'] = path_ids

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret['ret'] = 'fail'
            ret['log'] = str(e)
        finally:
            return ret
    
    @staticmethod
    def connect_test(url):
        try:
            ret = {}
            ret['ret'] = 'success'
            ret['current'] = len(LogicPikPak.get_status())
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret['ret'] = 'fail'
            ret['log'] = str(e)
        finally:
            return ret
    
    @staticmethod
    def program_init():
        try:
            ret = LogicPikPak.login()
            if ret['ret'] != 'success':
                data = '[로그인실패] PikPak 계정정보를 확인해주세요.'
                socketio.emit('notify', data, namespace='/framework', broadcast=True)
                return
            else:
                logger.debug(f'[PikPak 로그인성공] {ModelSetting.get("pikpak_username")}')

            try:
                import torrent_info
                LogicPikPak.torrent_info_installed = True
            except ImportError:
                pass

            #logger.debug(f'{dir(LogicPikPak.client)}')
            #logger.debug(f'{dir(PikPakApi)}')
            if ModelSetting.get('pikpak_default_path') != '':
                ret = LogicPikPak.path_to_id(ModelSetting.get('pikpak_default_path'), create=True)
                logger.debug(f'[PikPak: download_folder] {ret}')
                if ret['ret'] == 'success':
                    paths = ret['data']
                    LogicPikPak.download_folder_id = paths[-1]['id']
                else:
                    logger.error(f'[PikPak: 다운로드 폴더 오류{ret["log"]}')
            
            if ModelSetting.get('pikpak_upload_path') != '':
                ret = LogicPikPak.path_to_id(ModelSetting.get('pikpak_upload_path'), create=True)
                logger.debug(f'[PikPak: upload_folder] {ret}')
                if ret['ret'] == 'success':
                    paths = ret['data']
                    LogicPikPak.upload_folder_id = paths[-1]['id']
                else:
                    logger.error(f'[PikPak: 업로드 폴더 오류{ret["log"]}')

            upload_path_rule = {'default':ModelSetting.get('pikpak_upload_path')}
            if ModelSetting.get('pikpak_upload_path_rule') != '':
                try:
                    rules = ModelSetting.get_list('pikpak_upload_path_rule', '\n')
                    for rule in rules:
                        dn, up = rule.split('|')
                        upload_path_rule[dn] = up
                    LogicPikPak.upload_path_rule = upload_path_rule
                except Exception as e:
                    logger.error(f'[PikPak: 업로드 규칙 설정 오류: {e}')
                    msg = '업로드 경로 규칙을 설정해주세요'
                    socketio.emit('notify', msg, namespace='/framework', broadcast=True)

            if not LogicPikPak.MoveQueue: LogicPikPak.MoveQueue = py_queue.Queue()
            if not LogicPikPak.MoveThread:
                LogicPikPak.MoveThread = threading.Thread(target=LogicPikPak.move_thread_function, args=())
                LogicPikPak.MoveThread.daemon = True
                LogicPikPak.MoveThread.start()

            if not LogicPikPak.RemoveQueue: LogicPikPak.RemoveQueue = py_queue.Queue()
            if not LogicPikPak.RemoveThread:
                LogicPikPak.RemoveThread = threading.Thread(target=LogicPikPak.remove_thread_function, args=())
                LogicPikPak.RemoveThread.daemon = True
                LogicPikPak.RemoveThread.start()


        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def is_already_included(url):
        try:
            tasks = LogicPikPak.current_tasks
            if not tasks: tasks = LogicPikPak.get_status()
            for task in tasks:
                if task['params']['url'] == url:
                    return True

            # 요청목록 내 중복을 허용한 경우
            if ModelSetting.get_bool('pikpak_allow_dup'):
                return False

            if ModelDownloaderItem.get_by_download_url(url):
                return True

            return False

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_download(url, path):
        try:
            client = LogicPikPak.client

            if app.config['config']['is_py2']:
                path = path.encode('utf8')
            ret = {}

            # 중복 체크
            if LogicPikPak.is_already_included(url):
                ret['ret'] = 'error'
                ret['result'] = {'reason':f'중복 다운로드 요청으로 실패처리함({url},{path})'}
                logger.info(f'[download] 중복 다운로드 요청으로 실패처리함({url},{path}')
                return ret

            if path is not None and path.strip() == '':
                path = None

            parent_id = None
            if not path or ModelSetting.get('pikpak_default_path') == path:
                parent_id = LogicPikPak.download_folder_id
            else:
                ret = LogicPikPak.path_to_id(path, create=True)
                if ret['ret'] == 'success':
                    parent_id = ret['data'][-1]['id']

            ret['ret'] = 'success'
            if url.startswith('magnet:'):
                r = client.offline_download(file_url=url, parent_id=parent_id)
            else:
                if ModelSetting.get_bool('pikpak_use_torrent_info') and LogicPikPak.torrent_info_installed:
                    from torrent_info import Logic as TorrentInfo
                    try:
                        r = TorrentInfo.parse_torrent_url(url)
                        #logger.debug(f'torrent_info: {r}')
                        url = r['magnet_uri']
                        r = client.offline_download(file_url=url, parent_id=parent_id)
                    except RuntimeError:
                        logger.info(f'[download] torrent file 아님 일반다운로드 요청 처리({url})')
                        fname = os.path.split(url)[1]
                        fpath = os.path.join(path, fname)
                        logger.debug(f'일반파일 다운로드: {url}')
                        th = threading.Thread(target=LogicPikPak.download_thread_function, args=(url, fpath, parent_id))
                        th.start()
                        r = {'task': {'id': url, 'name': fname, 'file_id': fpath, 'file_name': fname}}
                else:
                    fname = os.path.split(url)[1]
                    fpath = os.path.join(path, fname)

                    logger.debug(f'일반파일 다운로드: {url}')
                    th = threading.Thread(target=LogicPikPak.download_thread_function, args=(url, fpath, parent_id))
                    th.start()
                    r = {'task': {'id': url, 'name': fname, 'file_id': fpath, 'file_name': fname}}

            logger.debug(f'[download] 작업추가: {r}')
            ret['result'] = r
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret['ret'] = 'error'
            ret['error'] = str(e)
        finally:
            ret['download_url'] = url
            ret['download_path'] = path if path is not None else ''
            return ret

    @staticmethod
    def get_filename_from_cd(cd):
        if not cd:
            return None
        fname = re.findall('filename=(.+)', cd)
        if len(fname) == 0:
            return None
        return fname[0].replace('"', '')

    @staticmethod
    def download_thread_function(url, fpath, parent_id):
        try:
            ret  = {}
            client = LogicPikPak.client

            r = requests.get(url, allow_redirects=True)
            filename = LogicPikPak.get_filename_from_cd(r.headers.get('content-disposition'))
            if not filename:
                filename = os.path.split(fpath)[1]
            
            filepath = os.path.join('/tmp', filename)
            logger.debug(f'[down-file] Direct download : {filepath}')
            open(filepath, 'wb').write(r.content)
            magnet_uri = LogicPikPak.get_magnet_uri_from_file(filepath)

            r = client.offline_download(file_url=magnet_uri, parent_id=parent_id)
            logger.debug(f'[download] 작업추가: {r}')
            item = ModelDownloaderItem.get_by_task_id(url)
            item.download_url = magnet_uri
            item.task_id = r['task']['id']
            task = LogicPikPak.get_status(task_id=item.task_id)
            item.file_id = task['file_id']
            item.title = task['name'] 
            if item.title == '': item.title = task['file_name']
            if r['task']['phase'] == 'PHASE_TYPE_RUNNING':
                item.status = 'downloading'
            item.update()
            if os.path.exists(filepath): os.remove(filepath)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def remove(task_id):
        try:
            item = ModelDownloaderItem.get_by_task_id(task_id)
            client = LogicPikPak.client
            login_headers = client.get_headers()
            task_text = f'task_ids={task_id}&'
            url = f"https://{client.PIKPAK_API_HOST}/drive/v1/tasks?{task_text}"
            res = requests.delete(url, headers=login_headers, proxies=client.proxy, timeout=5)
            if res.status_code == 200:
                logger.debug(f'[remove_job] 작업({task_id}) 삭제 완료({res.status_code})')
                if ModelSetting.get_bool('pikpak_remain_file_remove'):
                    logger.debug(f'[remove_job] 파일 삭제 요청({task_id})')
                    LogicPikPak.RemoveQueue.put({'task_id':task_id})
                return True
            
            logger.error(f'[remove_job] {task_id} 삭제 실패({res.status_code})')
            res.raise_for_status()

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return False

    status_thread = None
    status_thread_running = False

    @staticmethod
    def status_socket_connect():
        try:
            if LogicPikPak.status_thread is None:
                LogicPikPak.status_thread_running = True
                LogicPikPak.status_thread = threading.Thread(target=LogicPikPak.status_thread_function, args=())
                LogicPikPak.status_thread.start()
            data = LogicPikPak.get_status()
            #logger.debug(data)
            return data
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def status_thread_function():
        try:
            from .logic_normal import LogicNormal
            import copy
            status_interval = ModelSetting.get_int('status_interval')
            
            while LogicPikPak.status_thread_running:
                data = LogicPikPak.get_status()
                #logger.debug(f'[tasks] {data}')
                if LogicPikPak.prev_tasks != None:
                    for task in LogicPikPak.prev_tasks:
                        found = False
                        for item in data:
                            if item['id'] == task['id']:
                                found = True
                                break

                        # 완료되서 삭제된 항목 업데이트 
                        if not found:
                            ditem = ModelDownloaderItem.get_by_task_id(task['id'])
                            ditem.status = "completed"
                            ditem.completed_time = datetime.now()
                            ditem.update()
                            LogicNormal.send_telegram('4', ditem.title)

                for item in data:
                    ditem = ModelDownloaderItem.get_by_task_id(item['id'])
                    #logger.debug(f'ditem: {ditem}')
                    if not ditem: continue
                    if ditem.status == 'request' and item['progress'] > 0:
                        ditem.status = 'downloading'
                        #logger.debug(f'update: {ditem}')
                        ditem.update()

                LogicPikPak.prev_tasks = copy.deepcopy(data)
                socketio_callback(data)
                time.sleep(status_interval)

            logger.debug('status_thread_function end')
            LogicPikPak.status_thread = None
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def get_status(task_id = None):
        try:
            data = None
            while True:
                try:
                    data = LogicPikPak.client.offline_list()
                    if data: break
                except PikpakAccessTokenExpireException as e:
                    logger.warning('Exception:%s', e)
                    LogicPikPak.login()
                except Exception as e:
                    logger.warning('Exception:%s', e)
                    time.sleep(1)

            #logger.debug(f'{data}')
            if task_id:
                for task in data['tasks']:
                    if task['id'] == task_id:
                        return task

            return data['tasks']
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def scheduler_function():
        try:
            logger.debug('[Scheduler] PikPak 스케줄 함수 시작')

            from .logic_normal import LogicNormal
            auto_remove_completed = ModelSetting.get_bool('auto_remove_completed')

            logger.debug('[Scheduler] 완료된 항목 상태 갱신')
            tasks = LogicPikPak.get_status() # 이거 오류가 잦다
            LogicPikPak.current_tasks = tasks
            items = ModelDownloaderItem.get_by_program_and_status('4', 'completed', reverse=True)
            #logger.debug(f'[scheduler-items] {items}')
            logger.debug(f'[scheduler-tasks] {tasks}')
            for item in items:
                if item.status == 'moved': continue
                if item.status == 'removed': continue
                found = False
                flag_update = False
                # 진행중인 내역에 있는 경우 처리
                for task in tasks:
                    if item.download_url == task['params']['url'] and item.task_id == task['id']:
                        found = True
                        if task['progress'] >= 100:
                            item.status = "completed"
                            item.completed_time = datetime.now()
                            flag_update = True
                        elif task['progress'] > 0 and item.status != "downloading":
                            item.status = "downloading"
                            flag_update = True
                        else:
                            flag_update = False
                        break

                # 완료된 경우: 목록에서 자동으로 사라진다. 진행중인 내역에 없다면 완료된 것으로 판단
                if not found:
                    item.status = "completed"
                    item.completed_time = datetime.now()
                    flag_update = True

                if flag_update:
                    logger.debug(f'[Scheduler] 항목 갱신: {item.title}, {item.status}')
                    item.update()
                    LogicNormal.send_telegram('4', item.title)

            if ModelSetting.get_bool('pikpak_move_to_upload'):
                logger.debug('[Scheduler] 완료 항목 이동처리 시작')
                items = ModelDownloaderItem.get_by_program_and_status('4', 'completed')
                nitems = len(items)
                for item in items:
                    LogicPikPak.MoveQueue.put({'db_id':item.id})
                logger.debug(f'[Scheduler] 완료 항목 이동처리 요청완료:{nitems} 건')

            if ModelSetting.get_bool('pikpak_empty_trash'):
                logger.debug('[Scheduler] 휴지통 비우기 작업 시작')
                LogicPikPak.empty_trash()

            LogicPikPak.check_drive_quota()
            logger.debug('[Scheduler] PikPak 스케줄 작업 완료')

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def get_human_size(num, suffix="B"):
        for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
            if abs(num) < 1024.0:
                return f"{num:3.1f}{unit}{suffix}"
            num /= 1024.0
        return f'{num:.1f}Yi{suffix}'

    @staticmethod
    def check_drive_quota():
        try:
            client = LogicPikPak.client
            quota = LogicPikPak.get_quota_info()
            LogicPikPak.CurrentQuota = quota
            logger.debug(f'[quota] {LogicPikPak.CurrentQuota}')

            if ModelSetting.get_int('pikpak_quota_alert') > 0:
                limit = int(quota['quota']['limit'])
                use = int(quota['quota']['usage'])
                if int(use/limit*100) >= ModelSetting.get_int('pikpak_quota_alert'):
                    c = LogicPikPak.get_human_size(use)
                    l = LogicPikPak.get_human_size(limit)
                    per = 100 - round(use/limit*100, 2)
                    msg = f'[사용량 경고] PikPak 사용량이 {per}% 남았습니다.\n'
                    msg = msg + f'현재 사용량: {c}/{l}'
                    ToolBaseNotify.send_message(msg, message_id='pikpak_quota_alert')

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_download_status(file_id):
        try:
            client = LogicPikPak.client
            ret = client.offline_file_info(file_id)
            logger.debug(f'[get_download_status] {ret}')
            return {'ret': 'done', 'data':ret}
        except Exception as e: 
            logger.error('Exception:%s', e)
            if str(e).find('File or folder is not found') != -1:
                return {'ret':'not found'}
            logger.error(traceback.format_exc())
            return {'ret':'error'}

    @staticmethod
    def move_thread_function():
        try:
            logger.debug('[Move] Move Thread 시작')
            while True:
                req = LogicPikPak.MoveQueue.get()
                item = ModelDownloaderItem.get_by_id(int(req['db_id']))
    
                name = item.title
                file_id = item.file_id
                logger.debug(f'[Move] 이동작업 시작:({name}, {file_id})')
    
                down_status = LogicPikPak.get_download_status(file_id)
                if down_status['ret'] == 'not found':
                    fpath = os.path.join(item.download_path, item.title)
                    ret = LogicPikPak.path_to_id(fpath)
                    if ret['ret'] == 'success':
                        paths = ret['data']
                        if len(paths) != len(Util.get_list_except_empty(fpath.split('/'))):
                            logger.error(f'[Move] 이미삭제된 파일:({name}, {file_id})')
                            item.status = 'removed'
                            item.update()
                            LogicPikPak.MoveQueue.task_done()
                            continue
                        file_id = paths[-1]['id']
                        item.file_id = file_id
                        upload_path, parent_id = LogicPikPak.get_upload_path_info(item.download_path)
                    else:
                        logger.error(f'[Move] 이미삭제된 파일:({name}, {file_id})')
                        item.status = 'removed'
                        item.update()
                        LogicPikPak.MoveQueue.task_done()
                        continue
                elif down_status['ret'] == 'error':
                    logger.error(f'[Move] 파일정보 획득 실패:({name}, {file_id})')
                    LogicPikPak.MoveQueue.task_done()
                    continue
                else:
                    upload_path, parent_id = LogicPikPak.get_upload_path_info(item.download_path)

                    if down_status['data']['parent_id'] == parent_id:
                        logger.debug(f'[Move] 이미이동된 폴더: {name}')
                        LogicPikPak.MoveQueue.task_done()
                        continue
    
                result = LogicPikPak.move_file(file_id, parent_id)
                if not result:
                    logger.error(f'[Move] 파일이동 실패: {name}')
                    LogicPikPak.MoveQueue.task_done()
                    continue
    
                logger.debug(f'[Move] 이동작업 완료: {result}')
                item.status = 'moved'
                item.download_path = ModelSetting.get('pikpak_upload_path')
                item.update()
                LogicPikPak.MoveQueue.task_done()
    
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def remove_thread_function():
        logger.debug('[Remove] Remove Thread 시작')
        while True:
            try:
                req = LogicPikPak.RemoveQueue.get()
                task_id = req['task_id']
                item = ModelDownloaderItem.get_by_task_id(task_id)
    
                name = item.title
                file_id = item.file_id
                logger.debug(f'[Remove] 파일삭제 시작: {name},{file_id},{task_id})')

                if file_id == '':
                    file_path = os.path.join(item.download_path, item.title)
                    ret = LogicPikPak.path_to_id(file_path)
                    if ret['ret'] != 'success':
                        logger.warning(f'[Remove] 파일정보 획득 실패:({file_id})')
                        LogicPikPak.RemoveQueue.task_done()
                        continue

                target_id = ret['data'][-1]['id']
                ret = LogicPikPak.client.delete_to_trash([target_id])
                logger.debug(f'[Remove] 파일삭제 완료({ret})')
                item.status = 'removed'
                item.update()
                LogicPikPak.RemoveQueue.task_done()
    
            except Exception as e: 
                logger.error('[Remove] Exception:%s', e)
                logger.error(traceback.format_exc())
                LogicPikPak.RemoveQueue.task_done()

    @staticmethod
    def get_upload_path_info(download_path):
        try:
            upload_path = ModelSetting.get('pikpak_upload_path')
            rules = LogicPikPak.upload_path_rule
            if download_path in rules:
                upload_path = rules[download_path]

            if upload_path == ModelSetting.get('pikpak_upload_path'):
                return upload_path, LogicPikPak.upload_folder_id

            ret = LogicPikPak.path_to_id(upload_path, create=True)
            upload_folder_id = ret['data'][-1]['id']
            return upload_path, upload_folder_id

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return e

    @staticmethod
    def get_quota_info():
        try:
            client = LogicPikPak.client
            login_headers = client.get_headers()
            url = f"https://{client.PIKPAK_API_HOST}/drive/v1/about"
            result = requests.get(url=url, headers=login_headers,  timeout=5)

            if "error" in result.json():
                if result.json()['error_code'] == 16:
                    new_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    logger.info(f'INFO ({new_time}): 로그인 만료 재로그인')
                    client.login()
                    login_headers = client.get_headers()
                    result = requests.get(url=url, headers=login_headers, timeout=5)
                else:
                    new_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    logger.error(f"ERROR ({new_time}):f{result.json()['error_description']}")

            return result.json()

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return e

    @staticmethod
    def move_file(file_id, parent_id):
        try:
            client = LogicPikPak.client
            url = f"https://{client.PIKPAK_API_HOST}/drive/v1/files:batchMove"
            data = {"ids": [file_id], "to":{"parent_id": parent_id }}
            return LogicPikPak.client._request_post(url, data, client.get_headers(), client.proxy)

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return e

    @staticmethod
    def empty_trash():
        try:
            result = None
            next_page_token = None
            file_ids = list()
            while True:
                result = LogicPikPak.trash_list(next_page_token)
                if result:
                    #logger.debug(f'{result}')
                    next_page_token = result['next_page_token']
                    file_ids = file_ids + list(x['id'] for x in result['files'])
                    if next_page_token == '': break
                else:
                    time.sleep(1)
                    continue

            count = len(file_ids)
            logger.debug(f'[empty_trash] {count} 개의 아이템이 휴지통에 있음')
            result = None
            for i in range(0, count, 100):
                del_ids = file_ids[i:i+100]
                result = LogicPikPak.client.delete_forever(del_ids)
                logger.debug(f'[empty_trash] 휴지통 비우기 완료({i}~{len(del_ids)}, 결과({result})')
            
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def trash_list(page_token):
        client = LogicPikPak.client
        list_url = f"https://{client.PIKPAK_API_HOST}/drive/v1/files"
        list_data = {
            "parent_id": "*",
            "thumbnail_size": "SIZE_MEDIUM",
            "limit": 100,
            "with_audit": "true",
            "page_token": page_token,
            "filters": """{"trashed":{"eq":true},"phase":{"eq":"PHASE_TYPE_COMPLETE"}}""",
        }
        result = LogicPikPak.client._request_get(list_url, list_data, client.get_headers(), client.proxy)
        return result

    @staticmethod
    def get_magnet_uri_from_file(fpath):
        try:
            is_zip = False
            found = False
            fname, ext = os.path.splitext(fpath)
            torrent_path = None

            if ext == '.zip':
                import zipfile
                is_zip = True
                with zipfile.ZipFile(fpath, 'r') as zip_ref:
                    zip_ref.extractall('/tmp/')

                flist = zip_ref.namelist()
                for fname in flist:
                    if fname.lower().endswith('.torrent'):
                        found = True
                        torrent_path = os.path.join('/tmp', fname)
                        break
            elif ext.lower() == '.torrent':
                found = True
                torrent_path = fpath

            if found:
                try:
                    import magneturi
                except ImportError:
                    os.system("{} install magneturi".format(app.config['config']['pip']))
                    import magneturi

                magnet_uri = magneturi.from_torrent_file(torrent_path)
                logger.debug(f'magneturi: {magnet_uri}')
            else:
                logger.error(f'file not supported: {fpath}')
                magnet_uri = None

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

        finally:
            if is_zip:
                for fname in flist:
                    if os.path.exists(os.path.join('/tmp',fname)):
                        os.remove(os.path.join('/tmp',fname))
                zip_ref.close()
            return magnet_uri

# TODO
sid_list = []
@socketio.on('connect', namespace='/%s_pikpak' % package_name)
def connect():
    try:
        sid_list.append(request.sid)
        data = LogicPikPak.status_socket_connect()
        #logger.debug(data)
        socketio_callback(data)
        #emit('on_status', data, namespace='/%s' % package_name)

        #Logic.send_queue_start()
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())


@socketio.on('disconnect', namespace='/%s_pikpak' % package_name)
def disconnect():
    try:
        sid_list.remove(request.sid)
        if not sid_list:
            LogicPikPak.status_thread_running = False
        logger.debug('socket_disconnect')
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())

def socketio_callback(data):
    if sid_list:
        #logger.debug(data)
        tmp = json.dumps(data, cls=AlchemyEncoder)
        tmp = json.loads(tmp)
        socketio.emit('on_status', tmp , namespace='/%s_pikpak' % package_name, broadcast=True)
