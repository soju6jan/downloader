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
from datetime import datetime

from flask import Blueprint, request, Response, send_file, render_template, redirect, jsonify 
from flask_socketio import SocketIO, emit, send
from flask_login import login_user, logout_user, current_user, login_required

# sjva 공용
from framework import app, db, socketio
from framework.util import Util, AlchemyEncoder

# third-party
"""
from synolopy2 import NasApi

try:

    print("111111111111111111111111111")
    from synolopy2 import NasApi
except:
    print("22222222222222222222222")
    try:
        print("3333333333333333333333333")
        os.system("{} install synolopy".format(app.config['config']['pip']))
        print("555555555555555555555555555555")
        from synolopy import NasApi
    except:
        print("44444444444444444444444444")
        pass
print("6666666666666666666666666666")
"""


# 패키지
from .plugin import package_name, logger
from .model import ModelSetting, ModelDownloaderItem

#########################################################

class LogicDownloadStation(object):
    program = None

    @staticmethod
    def process_ajax(sub, req):
        try:
            if sub == 'test':
                downloadstation_url = req.form['downloadstation_url']
                downloadstation_id = req.form['downloadstation_id']
                downloadstation_pw = req.form['downloadstation_pw']
                ret = LogicDownloadStation.connect_test(downloadstation_url, downloadstation_id, downloadstation_pw)
                return jsonify(ret)
            elif sub == 'get_status':
                return jsonify(LogicDownloadStation.get_status())
            elif sub == 'remove':
                ds_id = request.form['id']
                data = LogicDownloadStation.remove(ds_id)
                return jsonify(data)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())



    @staticmethod
    def connect_test(url, id, pw):
        try:
            from synolopy2 import NasApi
            ret = {}
            nas = NasApi('%s/webapi/' % url, id, pw)
            data = nas.downloadstation.task.request('list')
            ret['ret'] = 'success'
            ret['current'] = data['total']
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
            from synolopy2 import NasApi
            url = ModelSetting.get('downloadstation_url')
            if url.strip() == '':
                return
            LogicDownloadStation.program = NasApi('%s/webapi/' % url, ModelSetting.get('downloadstation_id'), ModelSetting.get('downloadstation_pw'))
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def add_download(url, path):
        try:
            logger.debug(path)
            logger.debug([path])
            path = path.encode('utf8')
            ret = {}
            if path is not None and path.strip() == '':
                path = None
            if path is None:
                LogicDownloadStation.program.downloadstation.task.request('create', uri=url)
            else:
                LogicDownloadStation.program.downloadstation.task.request('create', uri=url, destination=path)
            ret['ret'] = 'success'
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
    def get_torrent_list():
        try:
            if LogicDownloadStation.program is None:
                return []
            data = LogicDownloadStation.program.downloadstation.task.request('list')
            id_list = []
            if not len(data['tasks']):
                return []
            for d in data['tasks']:
                id_list.append(d['id'])
            data = LogicDownloadStation.program.downloadstation.task.request('getinfo', id=','.join(id_list), additional='detail,transfer,file' )
            ret = data['tasks']
            if ret is None:
                ret = []
            return ret
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def remove(db_id):
        try:
            if LogicDownloadStation.program is None:
                return []
            data = LogicDownloadStation.program.downloadstation.task.request('Delete', id=db_id)
            return data
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    status_thread = None
    status_thread_running = False
    @staticmethod
    def status_socket_connect():
        try:
            if LogicDownloadStation.status_thread is None:
                LogicDownloadStation.status_thread_running = True
                LogicDownloadStation.status_thread = threading.Thread(target=LogicDownloadStation.status_thread_function, args=())
                LogicDownloadStation.status_thread.start()
            data = LogicDownloadStation.get_status()
            #logger.debug(data)
            return data
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def status_thread_function():
        try:
            status_interval = ModelSetting.get_int('status_interval')
            
            while LogicDownloadStation.status_thread_running:
                data = LogicDownloadStation.get_status()
                if ModelSetting.get_bool('auto_remove_completed'):
                    LogicDownloadStation.remove_completed(data)
                socketio_callback(data)
                #emit('on_status', data, namespace='/%s' % package_name)
                time.sleep(status_interval)
            logger.debug('status_thread_function end')
            LogicDownloadStation.status_thread = None
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def get_status():
        try:
            data = LogicDownloadStation.get_torrent_list()
            return data
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def scheduler_function():
        try:
            from .logic_normal import LogicNormal
            auto_remove_completed = ModelSetting.get_bool('auto_remove_completed')
            data = LogicDownloadStation.get_status()
            for item in data:
                downloader_item = db.session.query(ModelDownloaderItem).filter_by(download_url=item['additional']['detail']['uri']).filter_by(torrent_program='1').order_by(ModelDownloaderItem.id.desc()).first()
                
                if downloader_item is not None:
                    flag_update = False
                    if downloader_item.title == '' or downloader_item.title != item['title']:
                        downloader_item.title = item['title']
                        flag_update = True
                    if item['status'] == 5 or item['status'] == 'finished' or item['status'] == 8 or item['status'] == 'seeding':
                        logger.debug(downloader_item)
                        logger.debug(item)
                        if downloader_item.status != "completed":
                            downloader_item.status = "completed"
                            downloader_item.completed_time = datetime.now()
                            flag_update = True
                        if auto_remove_completed:
                            LogicDownloadStation.remove(item['id'])
                            LogicNormal.send_telegram('1', item['title'])
                    elif item['status'] == 'downloading' or item['status'] == 2:
                        if downloader_item.status != "downloading":
                            downloader_item.status = "downloading"
                            flag_update = True
                    elif item['status'] == 3:
                        if downloader_item.status != "stopped":
                            downloader_item.status = "stopped"
                            flag_update = True
                    elif item['status'] == 1:
                        if downloader_item.status != "waiting":
                            downloader_item.status = "waiting"
                            flag_update = True
                    else:
                        if downloader_item.status != item['status']:
                            downloader_item.status = item['status']
                            flag_update = True
                    if flag_update:
                        db.session.add(downloader_item)
                else:
                    if item['status'] == 'seeding' and auto_remove_completed:
                        LogicDownloadStation.remove(item['id'])
                        LogicNormal.send_telegram('1', item['title'])
            
            db.session.commit()
            if ModelSetting.get_bool('auto_remove_completed'):
                LogicDownloadStation.remove_completed(data)
            
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            
    @staticmethod
    def remove_completed(data):
        try:
            for item in data:
                if item['status'] == 5 or item['status'] == 'finished' or item['status'] == 8 or item['status'] == 'seeding':
                    downloader_item = db.session.query(ModelDownloaderItem).filter_by(download_url=item['additional']['detail']['uri']).filter_by(torrent_program='1').with_for_update().order_by(ModelDownloaderItem.id.desc()).first()
                    logger.debug('remove_completed2 %s', downloader_item)
                    if downloader_item is not None:
                        if downloader_item.status != "completed":
                            downloader_item.title = item['title']
                            downloader_item.status = "completed"
                            downloader_item.completed_time = datetime.now()
                            db.session.commit()
                    LogicDownloadStation.remove(item['id'])
                    from .logic_normal import LogicNormal
                    LogicNormal.send_telegram('1', item['title'])
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            

sid_list = []
@socketio.on('connect', namespace='/%s_downloadstation' % package_name)
def connect():
    try:
        sid_list.append(request.sid)
        data = LogicDownloadStation.status_socket_connect()
        #logger.debug(data)
        socketio_callback(data)
        #emit('on_status', data, namespace='/%s' % package_name)

        #Logic.send_queue_start()
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())


@socketio.on('disconnect', namespace='/%s_downloadstation' % package_name)
def disconnect():
    try:
        sid_list.remove(request.sid)
        if not sid_list:
            LogicDownloadStation.status_thread_running = False
        logger.debug('socket_disconnect')
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())

def socketio_callback(data):
    if sid_list:
        #logger.debug(data)
        tmp = json.dumps(data, cls=AlchemyEncoder)
        tmp = json.loads(tmp)
        socketio.emit('on_status', tmp , namespace='/%s_downloadstation' % package_name, broadcast=True)
