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

from flask import Blueprint, request, Response, send_file, render_template, redirect, jsonify, session, send_from_directory 
from framework import app, py_urllib, app
# 패키지
from .plugin import package_name, logger
from .model import ModelSetting, ModelDownloaderItem

#file move
import shutil




#########################################################

class LogicWatch(object):
    @staticmethod
    def process_ajax(sub, req):
        try:
            if sub == 'upload_torrent_file':
                ret = LogicWatch.upload_torrent_file(req)
                return jsonify(ret)
            elif sub == 'direct_execute':
                ret = LogicWatch.scheduler_function()
                return jsonify(True)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return jsonify(False)
    ##########################################################

    @staticmethod
    def scheduler_function():
        LogicWatch.search_from_torrent_file()

    @staticmethod
    def upload_torrent_file(request):
        #다운로드요청으로 넘어온 파일들
        logger.debug("upload_torrent_file")
        ret = None
        try:
            from .logic_normal import LogicNormal
            files = request.files

            #업로드 파일 임시폴더 저장
            tmp_file_list = []
            from framework import path_data
            tmp_file_path = os.path.join(path_data, 'tmp')
            #logger.debug("tmp_file_path : %s", tmp_file_path)
            for f in files.to_dict(flat=False)['attach_files[]']:
                tmp_upload_path = os.path.join(tmp_file_path, f.filename)
                logger.debug("tmp_upload_path : %s", tmp_upload_path)
                f.save(tmp_upload_path)
                #토렌트 추가 후 삭제할 경로 저장
                tmp_file_list.append(tmp_upload_path)

            #다운로드 요청에 필요한 값
            default_torrent_program = request.form['default_torrent_program'] if 'default_torrent_program' in request.form else None
            download_path = request.form['download_path'] if 'download_path'  in request.form else None

            #다운로드 요청
            if download_path is not None and download_path != '':
                for file in tmp_file_list:
                    if file.upper().find(".TORRENT") > -1:
                        magnet = LogicWatch.make_magnet_from_file(file)
                        logger.debug("upload_torrent_file() magnet : %s", magnet)
                        ret = LogicNormal.add_download2(magnet, default_torrent_program, download_path, request_type='download_request', request_sub_type='.torrent')
            
            #임시폴더에서 .torrent 파일 삭제
            logger.debug("delete torrent file from tmp folder")
            for file in tmp_file_list:
                logger.debug("tmp_file_path : %s", file)
                os.remove(file)

        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret = {'ret':'error'}
        finally:
            return ret
    
    @staticmethod
    def search_from_torrent_file():
        from .logic_normal import LogicNormal
        #감시폴더 조회
        logger.debug("start watch folder searching...")
        
        watch_upload_path = ModelSetting.get('watch_upload_path')
       
        # 2020-08-10 by soju6jan
        # 다운로드 경로는 빈값이 가능함. 비어있다면 최종 클라이언트 호출시 경로를 전달하지 않으며 이때는 토렌트 클라이언트 기본 다운로드 경로에 저장.
        # 윈도우는 거의 배제단계이지만, 아직 있긴함. 경로는 항상 os.path.join으로 
        # 다운로드 경로는 토렌트 기본값을 따르기로.. 여기서 None으로 호출하면 add_download2에서 체크함.
        if watch_upload_path != '':# and watch_download_path != '':
            fileList = os.listdir(watch_upload_path)
            for filename in fileList:
                # by soju. 파일 처리는 항상 try 사용
                try:
                    if filename.upper().find(".TORRENT") > -1:
                        filepath = os.path.join(watch_upload_path, filename)
                        magnet = LogicWatch.make_magnet_from_file(filepath)
                        logger.debug("search_from_torrent_file() magnet : %s", magnet)
                        
                        LogicNormal.add_download2(magnet, ModelSetting.get('watch_torrent_program'), None, request_type='.torrent', request_sub_type='.torrent')
                        #완료 된 경우 삭제 or 파일명 변환
                        if ModelSetting.get_bool("torrent_delete_yn"):
                            logger.debug("torrent_delete_yn : %s", torrent_delete_yn)
                            logger.debug("delete torrent file : %s", filepath)
                            os.remove(filepath)
                        else:
                            after_filename = file.replace(".torrent", ".complete", 1).replace(".TORRENT", ".complete", 1)
                            logger.debug("before name : %s, after name : %s", filename, after_filename)
                            #파일 이동
                            shutil.move(filepath, os.path,join(watch_upload_path, after_filename))
                except Exception as e: 
                    logger.error('Exception:%s', e)
                    logger.error(traceback.format_exc())
        else:
            logger.debug("watch_upload_path is Empty")
        logger.debug("finish watch folder searching...")


    @staticmethod
    def make_magnet_from_file(file):
        #torrent to magnet
        import hashlib
        import base64
        if app.config['config']['is_py2']:
            try:
                import bencode
            except:
                os.system("{} install bencode".format(app.config['config']['pip']))
                import bencode
            torrent = open(file, 'r').read()
            metadata = bencode.bdecode(torrent)

            hashcontents = bencode.bencode(metadata['info'])
            digest = hashlib.sha1(hashcontents).digest()
            b32hash = base64.b32encode(digest)

            params = {'xt': 'urn:btih:%s' % b32hash, 'dn': metadata['info']['name'], 'tr': metadata['announce'], 'xl': metadata['info']['length']}

            announcestr = ''
            for announce in metadata['announce-list']:
                announcestr += '&' + py_urllib.urlencode({'tr':announce[0]})

            paramstr = py_urllib.urlencode(params) + announcestr
            magneturi = 'magnet:?%s' % paramstr
            magneturi = magneturi.replace('xt=urn%3Abtih%3A', 'xt=urn:btih:', 1)
            logger.debug('magneturi : %s', magneturi)
            return magneturi
        else:
            try:
                import bencodepy
            except:
                os.system("{} install bencode.py".format(app.config['config']['pip']))
                import bencode
            torrent = open(file, 'r').read()
            metadata = bencodepy.decode(torrent)

            hashcontents = bencodepy.encode(metadata['info'])
            digest = hashlib.sha1(hashcontents).digest()
            b32hash = base64.b32encode(digest)

            params = {'xt': 'urn:btih:%s' % b32hash, 'dn': metadata['info']['name'], 'tr': metadata['announce'], 'xl': metadata['info']['length']}

            announcestr = ''
            for announce in metadata['announce-list']:
                announcestr += '&' + py_urllib.urlencode({'tr':announce[0]})

            paramstr = py_urllib.urlencode(params) + announcestr
            magneturi = 'magnet:?%s' % paramstr
            magneturi = magneturi.replace('xt=urn%3Abtih%3A', 'xt=urn:btih:', 1)
            logger.debug('magneturi : %s', magneturi)
            return magneturi
