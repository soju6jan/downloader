# -*- coding: utf-8 -*-
#########################################################
# python
import os
import traceback
import time
import threading

# third-party

# sjva 공용
from framework import db, scheduler, path_data
from framework.job import Job
from framework.util import Util

# 패키지
from .plugin import logger, package_name
from .model import ModelSetting, ModelDownloaderItem
from .logic_normal import LogicNormal
from .logic_transmission import LogicTransmission
#########################################################

class Logic(object):
    db_default = {
        'db_version' : '1',
        'auto_start' : 'False',
        'interval' : '10',
        'web_page_size': '30',
        'auto_remove_completed': 'True', 
        'status_interval' : '5',
        'download_completed_telegram_notify' : 'False',

        'default_torrent_program' : '0',

        'transmission_url' : '',
        'transmission_use_auth' : 'True',
        'transmission_id' : '',
        'transmission_pw' : '',
        'transmission_default_path' : '',
        'transmission_normal_file_download' : 'False',
        'transmission_normal_file_download_path' : '',
        
        'downloadstation_url' : '',
        'downloadstation_id' : '',
        'downloadstation_pw' : '',
        'downloadstation_default_path' : '',

        'qbittorrnet_url' : '',
        'qbittorrnet_id' : '',
        'qbittorrnet_pw' : '',
        'qbittorrnet_default_path' : '',
        'qbittorrnet_normal_file_download' : 'False',
        'qbittorrnet_normal_file_download_path' : '',

        #'aria2_url' : 'http://localhost/aria2/jsonrpc',
        'aria2_url' : '',
        'aria2_default_path' : os.path.join(path_data, 'aria2'),
    }

    @staticmethod
    def db_init():
        try:
            for key, value in Logic.db_default.items():
                if db.session.query(ModelSetting).filter_by(key=key).count() == 0:
                    db.session.add(ModelSetting(key, value))
            db.session.commit()
            Logic.migration()
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
        
    @staticmethod
    def plugin_load():
        try:
            logger.debug('%s plugin_load', package_name)
            Logic.db_init()
            LogicNormal.program_init()
            if ModelSetting.get_bool('auto_start'):
                Logic.scheduler_start()
            # 편의를 위해 json 파일 생성
            from plugin import plugin_info
            Util.save_from_dict_to_json(plugin_info, os.path.join(os.path.dirname(__file__), 'info.json'))
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def plugin_unload():
        try:
            logger.debug('%s plugin_unload', package_name)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    

    @staticmethod
    def scheduler_start():
        try:
            interval = ModelSetting.query.filter_by(key='interval').first().value
            job = Job(package_name, package_name, interval, Logic.scheduler_function, u"토렌트 다운로드 상태 체크", False)
            scheduler.add_job_instance(job)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    
    @staticmethod
    def scheduler_stop():
        try:
            scheduler.remove_job(package_name)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def scheduler_function():
        try:
            LogicNormal.scheduler_function()
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def reset_db():
        try:
            db.session.query(ModelDownloaderItem).delete()
            db.session.commit()
            return True
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return False


    @staticmethod
    def one_execute():
        try:
            if scheduler.is_include(package_name):
                if scheduler.is_running(package_name):
                    ret = 'is_running'
                else:
                    scheduler.execute_job(package_name)
                    ret = 'scheduler'
            else:
                def func():
                    time.sleep(2)
                    Logic.scheduler_function()
                threading.Thread(target=func, args=()).start()
                ret = 'thread'
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret = 'fail'
        return ret

    """
    @staticmethod
    def process_telegram_data(data):
        try:
            logger.debug(data)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    """
    
    @staticmethod
    def migration():
        try:
            pass
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    ############################################################


    # 타 플러그인

    @staticmethod
    def add_download2(download_url, default_torrent_program, download_path, request_type='web', request_sub_type=''):
        return LogicNormal.add_download2(download_url, default_torrent_program, download_path, request_type=request_type, request_sub_type=request_sub_type)
    
    @staticmethod
    def get_default_value():
        default_program = ModelSetting.get('default_torrent_program')
        default_path = ''
        if default_program == '0':
            default_path = ModelSetting.get('transmission_default_path')
        elif default_program == '1':
            default_path = ModelSetting.get('downloadstation_default_path')
        elif default_program == '2':
            default_path = ModelSetting.get('qbittorrnet_default_path')
        elif default_program == '3':
            default_path = ModelSetting.get('aria2_default_path')
        return default_program, default_path

    @staticmethod
    def is_available_normal_download():
        return True