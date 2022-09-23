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

# 패키지
from .plugin import package_name, logger
from .model import ModelSetting, ModelDownloaderItem

# pikpak
try:
    from pikpakapi import PikPakApi
except ImportError:
    os.system("{} install pikpakapi".format(app.config['config']['pip']))
    from pikpakapi import PikPakApi


#########################################################

class LogicPikPak(object):
    client = None
    download_folder_id = None
    upload_folder_id = None
    prev_tasks = None
    torrent_info_installed = False

    MoveThread = None
    MoveQueue = None

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
                data = LogicPikPak.remove(request.form['gid'])
                return jsonify(data)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    def login(username, password):
        try:
            ret = {}
            LogicPikPak.client = PikPakApi(username=username, password=password)
            while True:
                try:
                    LogicPikPak.client.login()
                    break
                except:
                    time.sleep(0.5)

            c = LogicPikPak.client
            logger.debug(f'{c.username},{c.user_id},{c.access_token},{c.refresh_token}')
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
                    if (f.get("kind", "") == "drive#folder" and f.get("name") == paths[count]):
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
            username = ModelSetting.get('pikpak_username')
            password = ModelSetting.get('pikpak_password')
            ret = LogicPikPak.login(username, password)
            if ret['ret'] != 'success':
                data = '[로그인실패] PikPak 계정정보를 확인해주세요.'
                socketio.emit('notify', data, namespace='/framework', broadcast=True)
                return
            else:
                logger.debug(f'[PikPak 로그인성공] {username}')

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

            if not LogicPikPak.MoveQueue: LogicPikPak.MoveQueue = py_queue.Queue()
            if not LogicPikPak.MoveThread:
                LogicPikPak.MoveThread = threading.Thread(target=LogicPikPak.move_thread_function, args=())
                LogicPikPak.MoveThread.daemon = True
                LogicPikPak.MoveThread.start()


        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def add_download(url, path):
        try:
            client = LogicPikPak.client

            if app.config['config']['is_py2']:
                path = path.encode('utf8')
            ret = {}
            if path is not None and path.strip() == '':
                path = None

            parent_id = None
            if not path or ModelSetting.get('pikpak_default_path') == path:
                parent_id = LogicPikPak.download_folder_id
            else:
                ret = LogicPikPak.path_to_id(path)
                if ret['ret'] == 'success':
                    parent_id = ret['data'][-1]['id']

            ret['ret'] = 'success'
            if url.startswith('magnet:'):
                r = client.offline_download(file_url=url, parent_id=parent_id)
            else:
                if ModelSetting.get_bool('pikpak_use_torrent_info') and LogicPikPak.torrent_info_installed:
                    from torrent_info import Logic as TorrentInfo
                    r = TorrentInfo.parse_torrent_url(url)
                    #logger.debug(f'torrent_info: {r}')
                    url = r['magnet_uri']
                    r = client.offline_download(file_url=url, parent_id=parent_id)
                else:
                    logger.debug('TODO: file download 처리 아직 미지원함')
                    msg = 'torrent 파일 링크를 통한 처리는 아직 지원하지 않습니다<br>torrent_info를 설치해주세요'
                    socketio.emit('notify', msg, namespace='/framework', broadcast=True)
                    ret['ret'] = 'failed'
                    r = {'reason':'not supported torrent file direct download yet'}

            logger.debug(f'add-result: {r}')
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
    def remove(gid):
        try:
            # pikpak 은 자동으로 목록에서 삭제됨 
            return True
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
    def get_status():
        try:
            data = None
            while True:
                try:
                    data = LogicPikPak.client.offline_list()
                    if data: break
                except Exception as e:
                    logger.warning('Exception:%s', e)
                    time.sleep(1)

            #logger.debug(f'{data}')
            return data['tasks']
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def refresh_access_token():
        try:
            client = LogicPikPak.client
            if not client:
                username = ModelSetting.get('pikpak_username')
                password = ModelSetting.get('pikpak_password')
                ret = LogicPikPak.login(username, password)
                if ret['ret'] == 'success':
                    return True
                else:
                    return False

            client.refresh_access_token()
            return True
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def scheduler_function():
        try:
            logger.debug('[Schduler] PikPak 스케줄 함수 시작')
            from .logic_normal import LogicNormal
            auto_remove_completed = ModelSetting.get_bool('auto_remove_completed')

            while True:
                if LogicPikPak.refresh_access_token():
                    break
                
                time.sleep(1)

            tasks = LogicPikPak.get_status() # 이거 오류가 잦다
            items = ModelDownloaderItem.get_by_program_and_status('4', 'completed', reverse=True)
            #logger.debug(f'[scheduler-items] {items}')
            #logger.debug(f'[scheduler-tasks] {tasks}')
            for item in items:
                if item.status == 'moved': continue
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
                        elif task['progress'] > 0:
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
                    item.update()
                    LogicNormal.send_telegram('4', item.title)

            if ModelSetting.get_bool('pikpak_empty_trash'):
                LogicPikPak.empty_trash()

            if ModelSetting.get_bool('pikpak_move_to_upload'):
                items = ModelDownloaderItem.get_by_program_and_status('4', 'completed')
                for item in items:
                    LogicPikPak.MoveQueue.put({'db_id':item.id})

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_download_status(file_id):
        try:
            client = LogicPikPak.client
            ret = client.offline_file_info(file_id)
            #logger.debug(f'[get_download_status] {ret}')
            return ret
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def move_thread_function():
        try:
            while True:
                logger.debug('[Move] Move Thread 시작')
                req = LogicPikPak.MoveQueue.get()
                item = ModelDownloaderItem.get_by_id(int(req['db_id']))
    
                name = item.title
                file_id = item.file_id
                logger.debug(f'[Move] 이동작업 시작:({name}, {file_id})')
    
                down_status = LogicPikPak.get_download_status(file_id)
                if not down_status:
                    logger.error(f'[Move] 파일정보 획득 실패:({name}, {file_id})')
                    LogicPikPak.MoveQueue.task_done()
                    return
                
                parent_id = LogicPikPak.upload_folder_id
                if not parent_id: parent_id = LogicPikPak.path_to_id(ModelSetting.get('pikpak_upload_path'), create=True)
                if down_status['parent_id'] == parent_id:
                    logger.debug(f'[Move] 이미이동된 폴더: {name}')
                    LogicPikPak.MoveQueue.task_done()
                    return
    
                result = LogicPikPak.move_file(file_id, parent_id)
                if not result:
                    raise(result)
                    return
    
                logger.debug(f'[Move] 이동작업 완료: {result}')
                item.status = 'moved'
                item.download_path = ModelSetting.get('pikpak_upload_path')
                item.update()
                LogicPikPak.MoveQueue.task_done()
    
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

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
                    logger.debug(f'{result}')
                    next_page_token = result['next_page_token']
                    file_ids = file_ids + list(x['id'] for x in result['files'])
                    if next_page_token == '': break
                else:
                    time.sleep(1)
                    continue

            count = len(file_ids)
            logger.debug(f'[empty_trash] {count} files in trash')
            result = None
            for i in range(0, count, 100):
                del_ids = file_ids[i:i+100]
                result = LogicPikPak.client.delete_forever(del_ids)
                logger.debug(f'[empty_trash] result({result})')
            
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
