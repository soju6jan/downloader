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
from framework import db, socketio
from framework.util import Util, AlchemyEncoder

# 패키지
from .plugin import package_name, logger
from .model import ModelSetting, ModelDownloaderItem

#########################################################


class LogicAria2(object):
    @staticmethod
    def jsonrpc(method, params=None):
        try:
            jsonreq = {'jsonrpc':'2.0', 'id':'sjva', 'method':method}
            if params is not None:
                jsonreq['params'] = params
            jsonreq = json.dumps(jsonreq)
            logger.debug(jsonreq)
            data = requests.get(ModelSetting.get('aria2_url'), data=jsonreq, headers={'Content-Type': 'application/json; charset=utf-8'}).json()
            return data
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def process_ajax(sub, req):
        try:
            if sub == 'test':
                url = req.form['aria2_url']
                ret = LogicAria2.connect_test(url, id, pw)
                return jsonify(ret)
            elif sub == 'get_status':
                return jsonify(LogicAria2.get_status())
            elif sub == 'remove':
                data = LogicAria2.remove(request.form['gid'])
                return jsonify(data)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def connect_test(url, id, pw):
        try:
            ret = {}
            ret['ret'] = 'success'
            ret['current'] = len(LogicAria2.get_status())
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
            pass
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def add_download(url, path):
        try:
            path = path.encode('utf8')
            ret = {}
            if path is not None and path.strip() == '':
                path = None

            if ModelSetting.get('aria2_url') == '':
                ret['ret'] = 'error'
                ret['error'] = 'aria2 접속 실패'
            else:
                LogicAria2.jsonrpc('aria2.addUri', params=[[url], {"dir":path}])
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
            #data = LogicAria2.jsonrpc('aria2.tellStatus')
            if ModelSetting.get('aria2_url') == '':
                return []
            jsonreq = json.dumps([
                {'jsonrpc':'2.0', 'id':'sjva', 'method':'aria2.tellActive'},
                {'jsonrpc':'2.0', 'id':'sjva', 'method':'aria2.tellWaiting', 'params':[0,1000]},
                {'jsonrpc':'2.0', 'id':'sjva', 'method':'aria2.tellStopped', 'params':[0,1000]}
            ])
            data = requests.get(ModelSetting.get('aria2_url'), data=jsonreq, headers={'Content-Type': 'application/json; charset=utf-8'}).json()
            ret = []
            for t1 in data:
                for tmp in t1['result']:
                    exist = False
                    for r in ret:
                        if 'infohash' in r:
                            if r['gid'] == tmp['gid'] or r['infoHash'] == tmp['infoHash']:
                                if r['name'] == r['infoHash']:
                                    ret.remove(r)
                                    break
                                else:
                                    exist = True
                                    break
                    if exist == False:
                        entity = {}
                        entity['gid'] = tmp['gid']
                        
                        entity['completedLength'] = tmp['completedLength']
                        entity['downloadSpeed'] = tmp['downloadSpeed']
                        entity['dir'] = tmp['dir']
                        entity['infoHash'] = tmp['infoHash'] if 'infohash' in tmp else ''
                        entity['status'] = tmp['status']
                        entity['totalLength'] = tmp['totalLength']
                        if 'bittorrent' in tmp:
                            if 'info' not in tmp['bittorrent']:
                                entity['name'] = tmp['infoHash']
                                entity['progress'] = 0
                            else:
                                entity['name'] = tmp['bittorrent']['info']['name']
                                entity['progress'] = float(entity['completedLength'])/float(entity['totalLength'])
                        else:
                            #logger.debug(tmp)
                            entity['name'] = os.path.basename(tmp['files'][0]['path'])
                            entity['progress'] = float(entity['completedLength'])/float(entity['totalLength'])
                        #logger.debug(tmp['bittorrent'])
                        ret.append(entity)
            return ret
        except Exception as e: 
            #logger.error('Exception:%s', e)
            #logger.error(traceback.format_exc())
            pass
        return []

    @staticmethod
    def remove(gid):
        try:
            jsonreq = json.dumps([
                {'jsonrpc':'2.0', 'id':'sjva', 'method':'aria2.remove', 'params':[gid]},
                {'jsonrpc':'2.0', 'id':'sjva', 'method':'aria2.removeDownloadResult', 'params':[gid]},
            ])
            data = requests.get(ModelSetting.get('aria2_url'), data=jsonreq, headers={'Content-Type': 'application/json; charset=utf-8'}).json()
            logger.debug(data)
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
            if LogicAria2.status_thread is None:
                LogicAria2.status_thread_running = True
                LogicAria2.status_thread = threading.Thread(target=LogicAria2.status_thread_function, args=())
                LogicAria2.status_thread.start()
            data = LogicAria2.get_status()
            #logger.debug(data)
            return data
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def status_thread_function():
        try:
            status_interval = ModelSetting.get_int('status_interval')
            
            while LogicAria2.status_thread_running:
                data = LogicAria2.get_status()
                if ModelSetting.get_bool('auto_remove_completed'):
                    LogicAria2.remove_completed(data)
                socketio_callback(data)
                #emit('on_status', data, namespace='/%s' % package_name)
                time.sleep(status_interval)
            logger.debug('status_thread_function end')
            LogicAria2.status_thread = None
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def get_status():
        try:
            data = LogicAria2.get_torrent_list()
            return data
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def scheduler_function():
        try:
            from .logic_normal import LogicNormal
            auto_remove_completed = ModelSetting.get_bool('auto_remove_completed')
            data = LogicAria2.get_status()
            for item in data:
                downloader_item = db.session.query(ModelDownloaderItem).filter(ModelDownloaderItem.download_url.like('%' + item['infoHash']+ '%')).filter_by(torrent_program='3').order_by(ModelDownloaderItem.id.desc()).first()

                if downloader_item is not None:
                    flag_update = False
                    if downloader_item.title != item['name']:
                        downloader_item.title = item['name']
                        flag_update = True
                    if item['progress'] >= 1: #100프로면 끝이라고봄
                        if downloader_item.status != "completed":
                            downloader_item.status = "completed"
                            downloader_item.completed_time = datetime.now()
                            flag_update = True
                        if auto_remove_completed:
                            LogicAria2.remove(item['gid'])
                            LogicNormal.send_telegram('3', item['name'])
                    elif item['status'] == 'downloading':
                        if downloader_item.status != "downloading":
                            downloader_item.status = "downloading"
                            flag_update = True
                    elif item['status'] == 'paused':
                        if downloader_item.status != "stopped":
                            downloader_item.status = "stopped"
                            flag_update = True
                    elif item['status'] == 'waiting':
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
                    if item['progress'] >= 1 and auto_remove_completed:
                        LogicAria2.remove(item['gid'])
                        LogicNormal.send_telegram('3', item['name'])
            
            db.session.commit()
            if ModelSetting.get_bool('auto_remove_completed'):
                LogicAria2.remove_completed(data)
            
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            
    @staticmethod
    def remove_completed(data):
        try:
            for item in data:
                if item['progress'] >= 1:
                    downloader_item = db.session.query(ModelDownloaderItem).filter(ModelDownloaderItem.download_url.like('%' + item['infoHash']+ '%')).filter_by(torrent_program='3').with_for_update().order_by(ModelDownloaderItem.id.desc()).first()
                    logger.debug('remove_completed2 %s', downloader_item)
                    if downloader_item is not None:
                        if downloader_item.status != "completed":
                            downloader_item.title = item['name']
                            downloader_item.status = "completed"
                            downloader_item.completed_time = datetime.now()
                            db.session.commit()
                    LogicAria2.remove(item['gid'])
                    from .logic_normal import LogicNormal
                    LogicNormal.send_telegram('3', item['name'])
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            

sid_list = []
@socketio.on('connect', namespace='/%s_aria2' % package_name)
def connect():
    try:
        sid_list.append(request.sid)
        data = LogicAria2.status_socket_connect()
        #logger.debug(data)
        socketio_callback(data)
        #emit('on_status', data, namespace='/%s' % package_name)

        #Logic.send_queue_start()
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())


@socketio.on('disconnect', namespace='/%s_aria2' % package_name)
def disconnect():
    try:
        sid_list.remove(request.sid)
        if not sid_list:
            LogicAria2.status_thread_running = False
        logger.debug('socket_disconnect')
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())

def socketio_callback(data):
    if sid_list:
        #logger.debug(data)
        tmp = json.dumps(data, cls=AlchemyEncoder)
        tmp = json.loads(tmp)
        socketio.emit('on_status', tmp , namespace='/%s_aria2' % package_name, broadcast=True)
