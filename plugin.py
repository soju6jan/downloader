# -*- coding: utf-8 -*-
#########################################################
# python
import os
import traceback
import time
from datetime import datetime
import urllib
import json
# third-party
import requests
from flask import Blueprint, request, Response, send_file, render_template, redirect, jsonify, session, send_from_directory 
from flask_socketio import SocketIO, emit, send
from flask_login import login_user, logout_user, current_user, login_required

# sjva 공용
from framework.logger import get_logger
from framework import app, db, scheduler, path_data, socketio, check_api
from framework.util import Util, AlchemyEncoder
from system.logic import SystemLogic

# 패키지
package_name = __name__.split('.')[0]
logger = get_logger(package_name)

from .model import ModelSetting, ModelDownloaderItem
from .logic import Logic
from .logic_normal import LogicNormal
from .logic_transmission import LogicTransmission
from .logic_downloadstation import LogicDownloadStation
from .logic_qbittorrent import LogicQbittorrent
from .logic_aria2 import LogicAria2
from .logic_watch import LogicWatch

#########################################################


#########################################################
# 플러그인 공용                                       
#########################################################
blueprint = Blueprint(package_name, package_name, url_prefix='/%s' %  package_name, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))

menu = {
    'main' : [package_name, u'다운로드 클라이언트'],
    'sub' : [
        ['setting', u'기본 설정'], ['watch', u'감시폴더'], ['request', u'다운로드 요청'], ['list', u'목록'], ['transmission', u'트랜스미션'], ['downloadstation', u'다운로드 스테이션'], ['qbittorrent', u'큐빗토렌트'], ['aria2', u'aria2'], ['log', u'로그']
    ], 
    'sub2' : {
        'transmission' : [
            ['setting', u'설정'], ['status', u'상태']
        ],
        'downloadstation' : [
            ['setting', u'설정'], ['status', u'상태']
        ],
        'qbittorrent' : [
            ['setting', u'설정'], ['status', u'상태']
        ],
        'aria2' : [
            ['setting', u'설정'], ['status', u'상태']
        ],
    },
    'category' : 'torrent'
}

plugin_info = {
    'version' : '0.1.0.0',
    'name' : 'downloader',
    'category_name' : 'torrent',
    'developer' : 'soju6jan',
    'description' : u'토렌트 다운로드 클라이언트 설정',
    'home' : 'https://github.com/soju6jan/downloader',
    'more' : '',
}


def plugin_load():
    Logic.plugin_load()

def plugin_unload():
    Logic.plugin_unload()

def process_telegram_data(data):
    LogicNormal.process_telegram_data(data)


#########################################################
# WEB Menu 
#########################################################
@blueprint.route('/')
def home():
    return redirect('/%s/request' % package_name)

@blueprint.route('/<sub>')
@login_required
def first_menu(sub): 
    logger.debug('DETAIL %s %s', package_name, sub)
    if sub == 'setting':
        arg = ModelSetting.to_dict()
        arg['scheduler'] = str(scheduler.is_include(package_name))
        arg['is_running'] = str(scheduler.is_running(package_name))
        arg['tracker_list'] = ModelSetting.get('tracker_list').replace('\n', ', ')
        return render_template('%s_%s.html' % (package_name, sub), arg=arg)
    elif sub in ['transmission', 'downloadstation', 'qbittorrent', 'aria2']:
        return redirect('/%s/%s/status' % (package_name, sub))
    elif sub in ['request', 'list', 'watch']:
        arg = ModelSetting.to_dict()
        arg['sub'] = sub
        return render_template('%s_%s.html' % (package_name, sub), arg=arg)
    elif sub == 'log':
        return render_template('log.html', package=package_name)
    return render_template('sample.html', title='%s - %s' % (package_name, sub))


# TODO : 
@blueprint.route('/<sub>/<sub2>')
@login_required
def second_menu(sub, sub2):
    try:
        if sub2 == 'setting':
            arg = ModelSetting.to_dict()
            arg['package_name'] = package_name
            arg['sub'] = sub
            arg['tracker_list'] = ModelSetting.get('tracker_list').replace('\n', ', ')
            return render_template('%s_%s_%s.html' % (package_name, sub, sub2), arg=arg)
        elif sub2 == 'status':
            arg = {}
            arg['package_name'] = package_name
            arg['sub'] = sub
            return render_template('%s_%s_%s.html' % (package_name, sub, sub2), arg=arg)
        return render_template('sample.html', title='%s - %s - %s' % (package_name, sub, sub2))
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())

#########################################################
# For UI 
#########################################################
@blueprint.route('/ajax/<sub>', methods=['GET', 'POST'])
@login_required
def ajax(sub):
    logger.debug('AJAX %s %s', package_name, sub)
    # 설정 저장
    try:
        if sub == 'setting_save':
            ret = ModelSetting.setting_save(request)
            LogicNormal.program_init()
            return jsonify(ret)
        elif sub == 'scheduler':
            go = request.form['scheduler']
            logger.debug('scheduler :%s', go)
            if go == 'true':
                Logic.scheduler_start()
            else:
                Logic.scheduler_stop()
            return jsonify(go)
        elif sub == 'one_execute':
            ret = Logic.one_execute()
            return jsonify(ret)
        elif sub == 'reset_db':
            ret = Logic.reset_db()
            return jsonify(ret)  

        #다운로드 요청
        elif sub == 'get_setting':
            return jsonify(ModelSetting.to_dict())  

        elif sub == 'add_download':
            ret = LogicNormal.add_download_by_request(request)
            return jsonify(ret)

        elif sub == 'web_list':
            ret = ModelDownloaderItem.web_list(request)
            return jsonify(ret)
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())  


@blueprint.route('/ajax/<sub>/<sub2>', methods=['GET', 'POST'])
@login_required
def second_ajax(sub, sub2):
    try:     
        if sub == 'transmission':
            return LogicTransmission.process_ajax(sub2, request)
        elif sub == 'downloadstation':
            return LogicDownloadStation.process_ajax(sub2, request)
        elif sub == 'qbittorrent':
            return LogicQbittorrent.process_ajax(sub2, request)
        elif sub == 'aria2':
            return LogicAria2.process_ajax(sub2, request)
        elif sub == 'watch':
            return LogicWatch.process_ajax(sub2, request)
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())

#########################################################
# API
#########################################################
@blueprint.route('/api/<sub>', methods=['GET', 'POST'])
@check_api
def api(sub):
    # 사용하는 곳이 있는가?
    # 2020-06-09 sjva.me에서 호출
    try:
        if sub == 'add_download':
            ret = LogicNormal.add_download_api(request)
            return jsonify(ret)
    except Exception as e: 
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())

