# -*- coding: utf-8 -*-
#########################################################
# python
import os
from datetime import datetime
import traceback
import logging
import subprocess
import time
import re
import json
import requests
import urllib
import urllib2
import lxml.html
from enum import Enum
import threading

# third-party
from sqlalchemy import desc
from sqlalchemy import or_, and_, func, not_
from telepot import Bot, glance
from telepot.loop import MessageLoop
from time import sleep
import telepot
from flask_socketio import SocketIO, emit, send

# sjva 공용
from framework.logger import get_logger
from framework import app, db, scheduler, path_app_root
from framework.job import Job
from framework.util import Util
from system.model import ModelSetting as SystemModelSetting
from system.logic import SystemLogic

# 패키지
from .plugin import logger, package_name
from .model import ModelSetting, ModelDownloaderItem
from .logic_transmission import LogicTransmission
from .logic_downloadstation import LogicDownloadStation
from .logic_qbittorrent import LogicQbittorrent
from .logic_aria2 import LogicAria2

import plugin


#########################################################

class LogicNormal(object):
    
   
    pre_telegram_title = None
    @staticmethod
    def send_telegram(where, title):
        try:
            if LogicNormal.pre_telegram_title == title:
                return
            else:
                LogicNormal.pre_telegram_title = title
            if where == '0':
                msg = '트랜스미션'
            elif where == '1':
                msg = '다운로드스테이션'
            elif where == '2':
                msg = '큐빗토렌트'
            elif where == '3':
                msg = 'aria2'
            msg += '\n%s 다운로드 완료' % title 
            import framework.common.notify as Notify
            Notify.send_message(msg, message_id='downloader_completed_remove')
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())



    @staticmethod
    def add_download_by_request(request):
        try:
            download_url = request.form['download_url'] if 'download_url' in request.form else None

            if download_url is None:
                return {'ret':'fail'}
            default_torrent_program = request.form['default_torrent_program'] if 'default_torrent_program' in request.form else None
            download_path = request.form['download_path'] if 'download_path'  in request.form else None

            return LogicNormal.add_download2(download_url, default_torrent_program, download_path)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret = {'ret':'error'}

    
    # 2020-08-04
    @staticmethod
    def add_download2(download_url, default_torrent_program, download_path, request_type='web', request_sub_type='', server_id=None):
        try:

            ######################## add name to magnet
            if ModelSetting.get_bool('use_download_name'):
                if "&dn=" not in download_url:
                    try:
                        data = {'uri': download_url}
                        url = '%s/torrent_info/api/json' % (SystemModelSetting.get('ddns'))
                        if SystemModelSetting.get_bool('auth_use_apikey'):
                            url += '?apikey=%s' % SystemModelSetting.get('auth_apikey')
                        
                        raw_info = requests.get(url, data).json()
                        if raw_info[u'success']:
                            download_url += '&dn=' + raw_info[u'info'][u'name']
                        # else:
                        #     #logger.debug("log: %d", str(raw_info[u'log']))
                    except:
                        pass
            ######################## torrent_tracker
            if ModelSetting.get_bool('use_tracker'):
                tracker_list = []
                tracker_list += [tracker.strip() for tracker in ModelSetting.get('tracker_list').split('\n') if len(tracker.strip()) != 0]
                tracker_list += [tracker.strip() for tracker in ModelSetting.get('tracker_list_manual').split('\n') if len(tracker.strip()) != 0]
                for tracker in tracker_list:
                    download_url += '&tr=' + tracker
            ########################

            setting_list = db.session.query(ModelSetting).all()
            arg = Util.db_list_to_dict(setting_list)
            if default_torrent_program is None:
                default_torrent_program = arg['default_torrent_program']
            

            if download_path is not None and download_path.strip() == '':
                download_path = None
            if default_torrent_program == '0':
                if download_path is None:
                    download_path = arg['transmission_default_path']
                download_path = LogicNormal.get_download_path(download_path, server_id, download_url)
                ret = LogicTransmission.add_download(download_url, download_path)
            elif default_torrent_program == '1':
                if download_path is None:
                    download_path = arg['downloadstation_default_path']
                download_path = LogicNormal.get_download_path(download_path, server_id, download_url)
                ret = LogicDownloadStation.add_download(download_url, download_path)
            elif default_torrent_program == '2':
                if download_path is None:
                    download_path = arg['qbittorrnet_default_path']
                download_path = LogicNormal.get_download_path(download_path, server_id, download_url)
                ret = LogicQbittorrent.add_download(download_url, download_path)
            elif default_torrent_program == '3':
                if download_path is None:
                    download_path = arg['aria2_default_path']
                download_path = LogicNormal.get_download_path(download_path, server_id, download_url)
                ret = LogicAria2.add_download(download_url, download_path)

            ret['default_torrent_program'] = default_torrent_program
            ret['downloader_item_id'] = ModelDownloaderItem.save(ret, request_type, request_sub_type)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret = {'ret':'error'}
        finally:
            return ret

    @staticmethod
    def get_download_path(download_path, server_id, download_url):
        logger.debug('download_path:%s server_id:%s', download_path, server_id)
        try:
            if server_id is not None and ModelSetting.get_bool('use_share_upload'):
                download_path = os.path.join(download_path, '%s_%s_%s' % (server_id, download_url[20:60].lower(), SystemModelSetting.get('sjva_me_user_id')))
                rule = ModelSetting.get('use_share_upload_make_dir_rule')
                if rule == '':
                    sjva_path = download_path
                else:
                    rule = rule.split('|')
                    sjva_path = download_path.replace(rule[0], rule[1])
                if os.path.exists(os.path.dirname(sjva_path)):
                    os.makedirs(sjva_path)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
        finally:
            logger.debug('download_path2:%s server_id:%s', download_path, server_id)
            return download_path

    @staticmethod
    def program_init():
        try:
            LogicTransmission.program_init()
            LogicDownloadStation.program_init()
            LogicQbittorrent.program_init()
            LogicAria2.program_init()
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return 'fail'
    


    @staticmethod
    def scheduler_function():
        try:
            logger.debug('scheduler_function')
            LogicTransmission.scheduler_function()
            LogicDownloadStation.scheduler_function()
            LogicQbittorrent.scheduler_function()
            LogicAria2.scheduler_function()
            
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())



    # sjva.me
    @staticmethod
    def add_download_api(req):
        try:
            logger.debug(req.form)
            url = req.form['url'] if 'url' in req.form else None
            subs = req.form['subs'] if 'subs' in req.form else None

            if subs is not None:
                for tmp in subs.split('|'):
                    ret = LogicNormal.add_download2(tmp, ModelSetting.get('default_torrent_program'), None, request_type='sjva.me', request_sub_type='sub')
            
            if url is not None and url.strip() != '':
                ret = LogicNormal.add_download2(url, ModelSetting.get('default_torrent_program'), None, request_type='sjva.me', request_sub_type='magnet')
            return ret
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
  
    

  

    @staticmethod
    def is_available_normal_download():
        try:
            ret = False
            default_torrent_program = db.session.query(ModelSetting).filter_by(key='default_torrent_program').first().value
            if default_torrent_program == '1':
                ret = True
            else:
                transmission_normal_file_download = (db.session.query(ModelSetting).filter_by(key='transmission_normal_file_download').first().value == 'True')
                ret = transmission_normal_file_download
            return ret
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    




    
   



    @staticmethod
    def filelist(req):
        try:
            ret = {}
            page = 1
            page_size = int(db.session.query(ModelSetting).filter_by(key='web_page_size').first().value)
            job_id = ''
            search = ''
            if 'page' in req.form:
                page = int(req.form['page'])
            if 'search_word' in req.form:
                search = req.form['search_word']
            
            query = db.session.query(ModelDownloaderItem)
            if search != '':
                query = query.filter(ModelDownloaderItem.title.like('%'+search+'%'))
            request_type = req.form['request_type']
            if request_type != 'all':
                query = query.filter(ModelDownloaderItem.request_type == request_type)
            count = query.count()
            query = (query.order_by(desc(ModelDownloaderItem.id))
                        .limit(page_size)
                        .offset((page-1)*page_size)
                )
            logger.debug('ModelDownloaderItem count:%s', count)
            lists = query.all()
            ret['list'] = [item.as_dict() for item in lists]
            ret['paging'] = Util.get_paging_info(count, page, page_size)
            return ret
        except Exception, e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

