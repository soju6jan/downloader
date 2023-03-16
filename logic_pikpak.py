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
from datetime import datetime, timedelta

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
            client = PikPakApi(username=username, password=password)
            try_cnt = 0
            while True:
                try:
                    try_cnt = try_cnt + 1
                    client.login()
                    if client.access_token != None: break
                    logger.warning(f'[로그인 실패] access_token is None(시도횟수: {try_cnt}')
                    if try_cnt > 10:
                        ret['ret'] = 'fail'
                        ret['log'] = 'failed to get access_token'
                        return ret
                    time.sleep(0.5)
                except Exception as e:
                    logger.warning('Exception:%s, retry login()', e)
                    time.sleep(0.5)

            LogicPikPak.client = client
            logger.debug(f'[로그인성공] {client.username},{client.user_id},access_token({client.access_token}),refresh_token({client.refresh_token})')
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
            cached = False
            cached_only = ModelSetting.get_bool('pikpak_cached_only')

            if url.startswith('magnet:'):
                if cached_only:
                    rlist = LogicPikPak.get_resource_list(url)
                    cached = LogicPikPak.is_cached(rlist)

                if cached_only == False or cached:
                    r = client.offline_download(file_url=url, parent_id=parent_id)
                else:
                    logger.debug(f'PikPak서버에 캐시가 존재하지 않아 대기처리({url})')
                    r = {'task': {'id': url, 'name':rlist['list']['resources'][0]['name'], 'file_id':'', 'status':'waiting'}}
            else:
                if ModelSetting.get_bool('pikpak_use_torrent_info') and LogicPikPak.torrent_info_installed:
                    from torrent_info import Logic as TorrentInfo
                    try:
                        r = TorrentInfo.parse_torrent_url(url)
                        #logger.debug(f'torrent_info: {r}')
                        url = r['magnet_uri']
                        if cached_only:
                            rlist = LogicPikPak.get_resource_list(url)
                            cached = LogicPikPak.is_cached(rlist)

                        if cached_only == False or cached:
                            r = client.offline_download(file_url=url, parent_id=parent_id)
                        else:
                            logger.debug(f'PikPak서버에 캐시가 존재하지 않아 대기처리({url})')
                            r = {'task': {'id': url, 'name':rlist['list']['resources'][0]['name'], 'file_id':'', 'status':'waiting'}}
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
            cached = False
            cached_only = ModelSetting.get_bool('pikpak_cached_only')

            r = requests.get(url, allow_redirects=True)
            filename = LogicPikPak.get_filename_from_cd(r.headers.get('content-disposition'))
            if not filename:
                filename = os.path.split(fpath)[1]
            
            filepath = os.path.join('/tmp', filename)
            logger.debug(f'[down-file] Direct download : {filepath}')
            open(filepath, 'wb').write(r.content)
            magnet_uri = LogicPikPak.get_magnet_uri_from_file(filepath)

            if cached_only:
                rlist = LogicPikPak.get_resource_list(magnet_uri)
                cached = LogicPikPak.is_cached(rlist)

            if cached_only == False or cached:
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
            else: # cache_only == True and cached == False 인 케이스
                item = ModelDownloaderItem.get_by_task_id(url)
                item.download_url = magnet_uri
                item.task_id = magnet_uri
                item.status = 'waiting'

            item.update()
            if os.path.exists(filepath): os.remove(filepath)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def remove(task_id, expired=False):
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
                    LogicPikPak.RemoveQueue.put({'task_id':task_id, 'expired':expired})
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
                            if ditem.status != 'expired':
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
                if item.status == 'expired': continue

                # 캐시대기 아이템 확인 및 처리
                if item.status == 'waiting':
                    logger.debug(f'[scheduler] 대기상태의 파일 처리 시작')
                    client = LogicPikPak.client
                    rlist = LogicPikPak.get_resource_list(item.download_url)
                    if not LogicPikPak.is_cached(rlist):
                        logger.debug(f'[scheduler] {item.title}: 캐시없음 - 대기처리')
                        continue
                    ret = LogicPikPak.path_to_id(item.download_path, create=True)
                    if ret['ret'] == 'success': parent_id = ret['data'][-1]['id']
                    r = client.offline_download(file_url=item.download_url, parent_id=parent_id)
                    logger.debug(f'[scheduler] {item.title}: 캐시확인 - 다운로드요청')
                    item.task_id = r['task']['id']
                    item.file_id = r['task']['file_id']
                    item.title = r['task']['name']
                    if item.title == '': item.title = r['result']['task']['file_name']
                    item.status = 'downloading'
                    item.update()
                    continue

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
                logger.debug('[Scheduler] 완료항목 이동처리 시작')
                items = ModelDownloaderItem.get_by_program_and_status('4', 'completed')
                nitems = len(items)
                for item in items:
                    LogicPikPak.MoveQueue.put({'db_id':item.id})
                logger.debug(f'[Scheduler] 완료항목 이동처리 요청완료:{nitems} 건')

            if ModelSetting.get_int('pikpak_expired_limit') > 0:
                logger.debug(f'[Scheduler] 만료항목 삭제처리 시작(기준시간: {ModelSetting.get("pikpak_expired_limit")}시간)')
                count = LogicPikPak.remove_expired()
                logger.debug(f'[Scheduler] 만료항목 삭제처리 요청완료({count} 건)')

            if ModelSetting.get_bool('pikpak_empty_trash'):
                logger.debug('[Scheduler] 휴지통 비우기 작업 시작')
                count = LogicPikPak.empty_trash()
                logger.debug(f'[Scheduler] 휴지통 비우기 작업 완료({count} 건)')

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
            #logger.debug(f'[quota] {LogicPikPak.CurrentQuota}')

            if ModelSetting.get_int('pikpak_quota_alert') > 0:
                limit = int(quota['quota']['limit'])
                use = int(quota['quota']['usage'])
                c = LogicPikPak.get_human_size(use)
                l = LogicPikPak.get_human_size(limit)
                per = 100 - round(use/limit*100, 2)
                logger.debug(f'[quota] 현재 사용량: {c}/{l} ({round(use/limit*100,2)}%)')
                if int(use/limit*100) >= ModelSetting.get_int('pikpak_quota_alert'):
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
    
                upload_path = None
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
                item.download_path = upload_path if not upload_path else ModelSetting.get('pikpak_upload_path')
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
                if 'expired' in req: expired = req['expired']
                else: expired = False
    
                name = item.title
                file_id = item.file_id
                logger.debug(f'[Remove] 파일삭제 시작: {name},{file_id},{task_id},expired({expired})')

                if file_id == '':
                    file_path = os.path.join(item.download_path, item.title)
                    ret = LogicPikPak.path_to_id(file_path)
                    if ret['ret'] != 'success':
                        logger.warning(f'[Remove] 파일정보 획득 실패:({file_id})')
                        LogicPikPak.RemoveQueue.task_done()
                        continue

                paths = ret['data']
                if len(paths) != len(Util.get_list_except_empty(file_path.split('/'))):
                    logger.error(f'[Remove] 이미삭제된 파일:({name}, {file_id})')
                else:
                    target_id = ret['data'][-1]['id']
                    ret = LogicPikPak.client.delete_to_trash([target_id])
                    logger.debug(f'[Remove] 파일삭제 완료({ret})')

                item.status = 'removed' if not expired else 'expired'
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
    def remove_expired():
        try:
            count = 0
            limit = ModelSetting.get_int('pikpak_expired_limit')
            items = ModelDownloaderItem.get_by_program_and_status('4', ['downloading','request'])
            now = datetime.now()
            remove_list = []
            for item in items:
                if (item.created_time + timedelta(hours=limit)) <= now:
                    over = now - item.created_time
                    logger.debug(f'[expired] {item.title} 다운로드 허용시간 만료({over})')
                    logger.debug(f'[expired] {item.title} 작업 및 파일 삭제 요청')
                    LogicPikPak.remove(item.task_id, expired=True)
                    remove_list.append(item.task_id)
                    count = count + 1

            tasks = LogicPikPak.get_status()
            for task in tasks:
                if task['id'] in remove_list: continue
                try:
                    tm_str = re.sub(r"[.]\d{3}[+]\d{2}[:]\d{2}$", "", task['created_time'])
                    created_time = datetime.strptime(tm_str, '%Y-%m-%dT%H:%M:%S')
                except ValueError:
                    logger.warning(f'[expired] {task["file_name"]} 시간파싱 오류({task["created_time"]})')
                    continue

                if (created_time + timedelta(hours=limit)) <= now:
                    over = now - created_time
                    logger.debug(f'[expired] {task["file_name"]} 다운로드 허용시간 만료({over})')
                    logger.debug(f'[expired] {task["file_name"]} 작업 및 파일 삭제 요청')
                    LogicPikPak.remove(task['id'], expired=True)
                    count = count + 1

            return count
            
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return -1

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
            #logger.debug(f'[empty_trash] {count} 개의 아이템이 휴지통에 있음')
            result = None
            for i in range(0, count, 100):
                del_ids = file_ids[i:i+100]
                result = LogicPikPak.client.delete_forever(del_ids)
                logger.debug(f'[empty_trash] 휴지통 비우기 완료({i}~{len(del_ids)}, 결과({result})')

            return count
            
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

    @staticmethod
    def is_cached(resource_list):
        try:
            if 'thumbnail_link' in resource_list['list']['resources'][0]['meta']:
                return True
            return False
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return False


    @staticmethod
    def get_resource_list(magnet):
        try:
            data = {}
            client = LogicPikPak.client
            data['urls'] = magnet
            data['page_size'] = 500
            data['thumbnail_type'] = "FROM_HASH"
            url = f"https://{client.PIKPAK_API_HOST}/drive/v1/resource/list"
            return client._request_post(url, data, client.get_headers(), client.proxy)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None



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
