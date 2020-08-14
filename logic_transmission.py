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

# third-party
try:
    import transmissionrpc
except:
    try:
        os.system('pip install transmissionrpc')
        import transmissionrpc
    except:
        pass

import requests
from flask import Blueprint, request, Response, send_file, render_template, redirect, jsonify, session, send_from_directory 
from flask_socketio import SocketIO, emit, send
from flask_login import login_user, logout_user, current_user, login_required

# sjva 공용
from framework.logger import get_logger
from framework import db, socketio
from framework.util import Util, AlchemyEncoder

# 패키지
from .plugin import package_name, logger
from .model import ModelSetting, ModelDownloaderItem


#########################################################


class LogicTransmission(object):
    program = None

    @staticmethod
    def process_ajax(sub, req):
        try:
            if sub == 'test':
                transmission_url = req.form['transmission_url']
                transmission_use_auth = req.form['transmission_use_auth']
                transmission_id = req.form['transmission_id']
                transmission_pw = req.form['transmission_pw']
                ret = LogicTransmission.connect_test(transmission_url, transmission_use_auth, transmission_id, transmission_pw)
                return jsonify(ret)
            elif sub == 'get_status':
                return jsonify(LogicTransmission.get_status())
            elif sub == 'remove':
                ds_id = req.form['id']
                include_data = (req.form['include_data'] == 'true')
                data = LogicTransmission.remove(ds_id, include_data=include_data)
                return jsonify(data)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def connect_test(url, use_auth, id, pw):
        try:
            ret = {}
            domain, port = LogicTransmission.get_domain_and_port_from_url(url)
            if use_auth:
                client = transmissionrpc.Client(domain, port, user=id, password=pw)
            else:
                client = transmissionrpc.Client(domain, port)
            ret['ret'] = 'success'
            ret['current'] = len(client.get_torrents())
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret['ret'] = 'fail'
            ret['log'] = str(e)
        finally:
            return ret




















    
    
    @staticmethod
    def get_domain_and_port_from_url(url):
        try:
            logger.debug(url)
            match = re.compile(r'(?P<protocol>http.*?\/\/)?(?P<hostname>[\w|\.\-]+)\:?(?P<port>\d+)?(?P<path>.*?)?$').match(url)
            #match = re.compile(r'(?P<protocol>http.*?\/\/)?(?P<hostname>.*?)\:?(?P<port>\d+)?(?P<path>.*?)?$').match(url)
            if match:
                protocol = match.group('protocol')
                hostname = match.group('hostname')
                port = match.group('port')
                path = match.group('path')
                if protocol is not None and protocol != '':
                    if port is not None and port != '':
                        ret_domain = '%s%s:%s/transmission/rpc' % (protocol, hostname, port)
                        ret_port = None
                    else:
                        ret_domain = '%s%s/transmission/rpc' % (protocol, hostname)
                        ret_port = None
                else:
                    ret_domain = hostname
                    ret_port = port
                    
                logger.debug('%s %s %s %s %s %s', protocol, hostname, port, path, ret_domain, ret_port)
                return ret_domain, ret_port
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    #def program_init(url, use_auth, user, pw):
    def program_init():
        url = ModelSetting.get('transmission_url')
        try:
            if url.strip() == '':
                return
            ret = {}
            domain, port = LogicTransmission.get_domain_and_port_from_url(url)
            if ModelSetting.get_bool('transmission_use_auth'):
                LogicTransmission.program = transmissionrpc.Client(domain, port, user=ModelSetting.get('transmission_id'), password=ModelSetting.get('transmission_pw'))
            else:
                LogicTransmission.program = transmissionrpc.Client(domain, port)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def add_download(url, path):
        ret = {}
        try:
            if not url.startswith('magnet') and not url.endswith('.torrent'):
                if ModelSetting.get_bool('transmission_normal_file_download'):
                    #2020-08-14
                    # 공유용이라면  대응되는 sjva 쪽 경로에 받도록한다.
                    if ModelSetting.get_bool('use_share_upload'):
                        #path는 토렌트프로그램상의 경로
                        rule = ModelSetting.get('use_share_upload_make_dir_rule').split('|')
                        path = path.replace(rule[0], rule[1])
                    else:
                        path = ModelSetting.get('transmission_normal_file_download_path')
                    th = threading.Thread(target=LogicTransmission.download_thread_function, args=(url, path))
                    th.start()
                    ret['ret'] = 'success2'
                else:
                    ret['ret'] = 'fail'
                logger.debug('normal file downerload:%s', ret)
                return ret
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

        try:
            
            if LogicTransmission.program is None:
                LogicTransmission.program_init()
            if LogicTransmission.program is None:
                ret['ret'] = 'error'
                ret['error'] = '트랜스미션 접속 실패'
            
            if path is not None and path.strip() == '':
                path = None
            if path is None:
                obj = LogicTransmission.program.add_torrent(url)
            else:
                obj = LogicTransmission.program.add_torrent(url, download_dir=path)
            
            if isinstance(obj, transmissionrpc.Torrent):
                ret['ret'] = 'success'
            else:
                ret['ret'] = 'fail'
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret['ret'] = 'error'
            ret['error'] = str(e)
        ret['download_url'] = url
        ret['download_path'] = path if path is not None else ''
        logger.debug(ret)
        return ret
        # 2020-07-23 자막파일일때 에러리턴 안함.
        """
        try:
            if ret['ret'] == 'error' and ret['error'].find('invalid or corrupt torrent file') != -1:
                if ModelSetting.get_bool('transmission_normal_file_download'):
                    th = threading.Thread(target=LogicTransmission.download_thread_function, args=(url, ModelSetting.get('transmission_normal_file_download_path')))
                    th.start()
                    ret['ret'] = 'success2'
            return ret
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
        finally:
            return ret
        """

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
            r = requests.get(url, allow_redirects=True)
            filename = LogicTransmission.get_filename_from_cd(r.headers.get('content-disposition'))
            filepath = os.path.join(download_path, filename)
            logger.debug('Direct download : %s', filepath)
            open(filepath, 'wb').write(r.content)
            data = {'type':'success', 'msg' : u'다운로드 성공<br>' + filepath}
        except Exception as e: 
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
            if LogicTransmission.program is None:
                return []
            data = LogicTransmission.program.get_torrents()
            ret = []
            for t in data:
                ret.append(LogicTransmission.get_dict(t))
            #logger.debug(data)
            #logger.debug(ret)
            return ret
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def remove(db_id, include_data=False):
        try:
            if LogicTransmission.program is None:
                return []
            LogicTransmission.program.remove_torrent(db_id, delete_data=include_data)
            return True
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return False


    @staticmethod
    def get_dict(torrent):
        ret = {}
        ret['id'] = torrent.id
        ret['status'] = torrent.status.lower()
        try:
            ret['title'] = torrent._get_name_string().decode('utf8')
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret['title'] = torrent._get_name_string()
        ret['percentDone'] = torrent.percentDone
        #ret['sizeWhenDone'] = torrent.sizeWhenDone
        ret['totalSize'] = torrent.totalSize
        ret['uploadedEver'] = torrent.uploadedEver #업로드 량 
        #ret['uploadRatio'] = torrent.uploadRatio
        #ret['pieceSize'] = torrent.pieceSize
        #downloadedEver
        ret['downloadedEver'] = torrent.downloadedEver
        ret['rateDownload'] = torrent.rateDownload
        tmp = torrent.magnetLink
        #logger.debug(tmp)
        if tmp.startswith('magnet'):
            ret['url'] = tmp[:60]
        else:
            ret['url'] = tmp
        return ret

    
    status_thread = None
    status_thread_running = False
    @staticmethod
    def status_socket_connect():
        try:
            if LogicTransmission.status_thread is None:
                LogicTransmission.status_thread_running = True
                LogicTransmission.status_thread = threading.Thread(target=LogicTransmission.status_thread_function, args=())
                LogicTransmission.status_thread.start()
            data = LogicTransmission.get_status()
            #logger.debug(data)
            return data
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def status_thread_function():
        try:
            status_interval = ModelSetting.get_int('status_interval')
            
            while LogicTransmission.status_thread_running:
                data = LogicTransmission.get_status()
                if ModelSetting.get_bool('auto_remove_completed'):
                    LogicTransmission.remove_completed(data)
                socketio_callback(data)
                #emit('on_status', data, namespace='/%s' % package_name)
                time.sleep(status_interval)
            logger.debug('status_thread_function end')
            LogicTransmission.status_thread = None
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def get_status():
        try:
            data = LogicTransmission.get_torrent_list()
            return data
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def scheduler_function():
        try:
            from .logic_normal import LogicNormal
            auto_remove_completed = ModelSetting.get_bool('auto_remove_completed')
            data = LogicTransmission.get_status()
            for item in data:
                downloader_item = db.session.query(ModelDownloaderItem).filter_by(download_url=item['url']).filter_by(torrent_program='0').order_by(ModelDownloaderItem.id.desc()).first()
                logger.debug(item)
                if downloader_item is not None:
                    flag_update = False
                    #if downloader_item.title == '':
                    if downloader_item.title != item['title']:
                        downloader_item.title = item['title']
                        flag_update = True
                    if item['status'] == 'seeding' or item['status'] == 'finished' or item['percentDone'] == 1:
                        if downloader_item.status != "completed":
                            downloader_item.status = "completed"
                            downloader_item.completed_time = datetime.now()
                            flag_update = True
                        if auto_remove_completed:
                            LogicTransmission.remove(item['id'])
                            LogicNormal.send_telegram('0', item['title'])
                    elif item['status'] == 'downloading':
                        if downloader_item.status != "downloading":
                            downloader_item.status = "downloading"
                            flag_update = True
                    elif item['status'] == 'stopped':

                        if downloader_item.status != "stopped":
                            downloader_item.status = "stopped"
                            flag_update = True
                        if item['percentDone'] == 1:
                            downloader_item.status = "completed"
                            downloader_item.completed_time = datetime.now()
                            flag_update = True
                            if auto_remove_completed:
                                LogicTransmission.remove(item['id'])
                                LogicNormal.send_telegram('0', item['title'])
                    elif item['status'] == 'download pending':
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
                        LogicTransmission.remove(item['id'])
                        LogicNormal.send_telegram('0', item['title'])
            db.session.commit()
            if ModelSetting.get_bool('auto_remove_completed'):
                LogicTransmission.remove_completed(data)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def remove_completed(data):
        try:
            for item in data:
                #if item['status'] == 'seeding':
                if item['percentDone'] == 1:
                    downloader_item = db.session.query(ModelDownloaderItem).filter_by(download_url=item['url']).filter_by(torrent_program='0').with_for_update().order_by(ModelDownloaderItem.id.desc()).first()
                    if downloader_item is not None:
                        if downloader_item.status != "completed":
                            downloader_item.title = item['title']
                            downloader_item.status = "completed"
                            downloader_item.completed_time = datetime.now()
                            db.session.commit()
                    LogicTransmission.remove(item['id'])
                    from .logic_normal import LogicNormal
                    LogicNormal.send_telegram('0', item['title'])
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())




sid_list = []
@socketio.on('connect', namespace='/%s_transmission' % package_name)
def connect():
    try:
        sid_list.append(request.sid)
        data = LogicTransmission.status_socket_connect()
        socketio_callback(data)
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())


@socketio.on('disconnect', namespace='/%s_transmission' % package_name)
def disconnect():
    try:
        sid_list.remove(request.sid)
        if not sid_list:
            LogicTransmission.status_thread_running = False
        logger.debug('socket_disconnect')
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())

def socketio_callback(data):
    if sid_list:
        tmp = json.dumps(data, cls=AlchemyEncoder)
        tmp = json.loads(tmp)
        socketio.emit('on_status', tmp , namespace='/%s_transmission' % package_name, broadcast=True)
