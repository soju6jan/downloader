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
import requests

# third-party
try:
    from qbittorrent import Client
except:
    try:
        os.system("{} install python-qbittorrent".format(app.config['config']['pip']))
        from qbittorrent import Client
    except:
        pass


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

class LogicQbittorrent(object):
    program = None

    @staticmethod
    def process_ajax(sub, req):
        try:
            if sub == 'test':
                url = req.form['qbittorrnet_url']
                id = req.form['qbittorrnet_id']
                pw = req.form['qbittorrnet_pw']
                ret = LogicQbittorrent.connect_test(url, id, pw)
                return jsonify(ret)
            elif sub == 'get_status':
                return jsonify(LogicQbittorrent.get_status())
            elif sub == 'remove':
                data = LogicQbittorrent.remove(request.form['hash'], (req.form['include_data'] == 'true'))
                return jsonify(data)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def connect_test(url, id, pw):
        try:
            ret = {}
            qb = Client(url)
            qb.login(id, pw)
            torrents = qb.torrents()
            ret['ret'] = 'success'
            ret['current'] = len(torrents)
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
            url = ModelSetting.get('qbittorrnet_url')
            if url.strip() == '':
                return
            LogicQbittorrent.program = Client(url)
            LogicQbittorrent.program.login(ModelSetting.get('qbittorrnet_id'), ModelSetting.get('qbittorrnet_pw'))
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
            if ModelSetting.get_bool('qbittorrnet_normal_file_download') and url.startswith('http'):
                #2020-08-24
                # 공유용이라면  대응되는 sjva 쪽 경로에 받도록한다.
                if ModelSetting.get_bool('use_share_upload'):
                    #path는 토렌트프로그램상의 경로
                    tmp = ModelSetting.get('use_share_upload_make_dir_rule')
                    if tmp != '':
                        rule = tmp.split('|')
                        path = path.replace(rule[0], rule[1])
                else:
                    path = ModelSetting.get('qbittorrnet_normal_file_download_path')
                logger.debug(u'일반파일 다운로드 경로 : %s', path)
                th = threading.Thread(target=LogicQbittorrent.download_thread_function, args=(url, path))
                th.start()
                ret['ret'] = 'success2'
                #th = threading.Thread(target=LogicQbittorrent.download_thread_function, args=(url,))
                #th.start()
                #ret['ret'] = 'success2'
            else:
                if LogicQbittorrent.program is None:
                    LogicQbittorrent.program_init()
                if LogicQbittorrent.program is None:
                    ret['ret'] = 'error'
                    ret['error'] = '큐빗토렌트 접속 실패'
                else:
                    if path is None:
                        tmp = LogicQbittorrent.program.download_from_link(url)
                    else:
                        tmp = LogicQbittorrent.program.download_from_link(url, savepath=path)
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
    def get_filename_from_cd(cd):
        """
        Get filename from content-disposition
        """
        if not cd:
            return None
        fname = re.findall('filename=(.+)', cd)
        if len(fname) == 0:
            return None
        return fname[0].replace('"', '')

    @staticmethod
    def download_thread_function(url, download_path):
        try:
            #download_path = ModelSetting.get('qbittorrnet_normal_file_download_path')
            r = requests.get(url, allow_redirects=True)
            filename = LogicQbittorrent.get_filename_from_cd(r.headers.get('content-disposition'))
            if not os.path.exists(download_path):
                os.makedirs(download_path)
            filepath = os.path.join(download_path, filename)
            logger.debug('Direct download : %s', filepath)
            open(filepath, 'wb').write(r.content)
            data = {'type':'success', 'msg' : u'다운로드 성공<br>' + filepath}
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            data = {'type':'warning', 'msg' : u'다운로드 실패<br>' + filepath, 'url':'/downloader/list'}
            try:
                logger.error('Exception:%s', e)
            except:
                pass
            #logger.error(traceback.format_exc())
        finally:
            socketio.emit("notify", data, namespace='/framework', broadcast=True) 


    @staticmethod
    def get_torrent_list():
        try:
            if LogicQbittorrent.program is None:
                return []
            ret = LogicQbittorrent.program.torrents()
            return ret
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def remove(hash, include_data=False):
        try:
            if LogicQbittorrent.program is None:
                return []
            if include_data:
                data = LogicQbittorrent.program.delete_permanently(hash)
            else:
                data = LogicQbittorrent.program.delete(hash)
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
            if LogicQbittorrent.status_thread is None:
                LogicQbittorrent.status_thread_running = True
                LogicQbittorrent.status_thread = threading.Thread(target=LogicQbittorrent.status_thread_function, args=())
                LogicQbittorrent.status_thread.start()
            data = LogicQbittorrent.get_status()
            #logger.debug(data)
            return data
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def status_thread_function():
        try:
            status_interval = ModelSetting.get_int('status_interval')
            
            while LogicQbittorrent.status_thread_running:
                data = LogicQbittorrent.get_status()
                if ModelSetting.get_bool('auto_remove_completed'):
                    LogicQbittorrent.remove_completed(data)
                socketio_callback(data)
                #emit('on_status', data, namespace='/%s' % package_name)
                time.sleep(status_interval)
            logger.debug('status_thread_function end')
            LogicQbittorrent.status_thread = None
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def get_status():
        try:
            data = LogicQbittorrent.get_torrent_list()
            return data
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def scheduler_function():
        try:
            from .logic_normal import LogicNormal
            auto_remove_completed = ModelSetting.get_bool('auto_remove_completed')
            data = LogicQbittorrent.get_status()
            for item in data:
                #downloader_item = db.session.query(ModelDownloaderItem).filter_by(download_url=item['additional']['detail']['uri']).filter_by(torrent_program='1').order_by(ModelDownloaderItem.id.desc()).first()
                downloader_item = db.session.query(ModelDownloaderItem).filter(ModelDownloaderItem.download_url.like(item['magnet_uri'].split('&')[0]+ '%')).filter_by(torrent_program='2').order_by(ModelDownloaderItem.id.desc()).first()

                if downloader_item is not None:
                    flag_update = False
                    if downloader_item.title != item['name']:
                        downloader_item.title = item['name']
                        flag_update = True
                    if LogicQbittorrent.is_completed(item):
                        if downloader_item.status != "completed":
                            downloader_item.status = "completed"
                            downloader_item.completed_time = datetime.now()
                            flag_update = True
                        if auto_remove_completed:
                            LogicQbittorrent.remove(item['hash'])
                            LogicNormal.send_telegram('2', item['name'])
                    elif item['state'] == 'downloading':
                        if downloader_item.status != "downloading":
                            downloader_item.status = "downloading"
                            flag_update = True
                    elif item['state'] == 'pausedDL':
                        if downloader_item.status != "stopped":
                            downloader_item.status = "stopped"
                            flag_update = True
                    elif item['state'] == 'queuedDL':
                        if downloader_item.status != "waiting":
                            downloader_item.status = "waiting"
                            flag_update = True
                    else:
                        if downloader_item.status != item['state']:
                            downloader_item.status = item['state']
                            flag_update = True
                    if flag_update:
                        db.session.add(downloader_item)
                else:
                    if LogicQbittorrent.is_completed(item) and auto_remove_completed:
                        LogicQbittorrent.remove(item['hash'])
                        LogicNormal.send_telegram('2', item['name'])
            
            db.session.commit()
            if ModelSetting.get_bool('auto_remove_completed'):
                LogicQbittorrent.remove_completed(data)
            
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def is_completed(data):
        return (data['progress'] == 1 and data['state'] in ['uploading', 'pausedUP', 'stalledUP', 'checkingUP', 'queuedUP'])


    @staticmethod
    def remove_completed(data):
        try:
            for item in data:
                if LogicQbittorrent.is_completed(item):
                    #downloader_item = db.session.query(ModelDownloaderItem).filter_by(download_url=item['additional']['detail']['uri']).filter_by(torrent_program='1').with_for_update().order_by(ModelDownloaderItem.id.desc()).first()
                    downloader_item = db.session.query(ModelDownloaderItem).filter(ModelDownloaderItem.download_url.like(item['magnet_uri'].split('&')[0]+ '%')).filter_by(torrent_program='2').with_for_update().order_by(ModelDownloaderItem.id.desc()).first()
                    logger.debug('remove_completed2 %s', downloader_item)
                    if downloader_item is not None:
                        if downloader_item.status != "completed":
                            downloader_item.title = item['name']
                            downloader_item.status = "completed"
                            downloader_item.completed_time = datetime.now()
                            db.session.commit()
                    LogicQbittorrent.remove(item['hash'])
                    from .logic_normal import LogicNormal
                    LogicNormal.send_telegram('2', item['name'])
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            

sid_list = []
@socketio.on('connect', namespace='/%s_qbittorrent' % package_name)
def connect():
    try:
        sid_list.append(request.sid)
        data = LogicQbittorrent.status_socket_connect()
        socketio_callback(data)
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())


@socketio.on('disconnect', namespace='/%s_qbittorrent' % package_name)
def disconnect():
    try:
        sid_list.remove(request.sid)
        if not sid_list:
            LogicQbittorrent.status_thread_running = False
        logger.debug('socket_disconnect')
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())

def socketio_callback(data):
    if sid_list:
        tmp = json.dumps(data, cls=AlchemyEncoder)
        tmp = json.loads(tmp)
        socketio.emit('on_status', tmp , namespace='/%s_qbittorrent' % package_name, broadcast=True)
