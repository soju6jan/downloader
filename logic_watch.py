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

# 패키지
from .plugin import package_name, logger
from .model import ModelSetting, ModelDownloaderItem

#file move
import shutil

#torrent to magnet
import sys
import urllib
try:
    import bencode
except:
    os.system("pip install bencode")
    import bencode
import hashlib
import base64

#########################################################

class LogicWatch(object):
    
    @staticmethod
    def scheduler_function():
        LogicWatch.search_from_torrent_file()

    @staticmethod
    def upload_torrent_file(request):
        #다운로드요청으로 넘어온 파일들
        logger.debug("upload_torrent_file")
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
            if download_path not None and download_path != '':
                for file in tmp_file_list:
                    if file.upper().find(".TORRENT") > -1:
                        magnet = LogicWatch.make_magnet_from_file(file)
                        logger.debug("upload_torrent_file() magnet : %s", magnet)
                        LogicNormal.add_download2(magnet, default_torrent_program, download_path, request_type='download_request', request_sub_type='download_request')
            
            #임시폴더에서 .torrent 파일 삭제
            logger.debug("delete torrent file from tmp folder")
            for file in tmp_file_list:
                logger.debug("tmp_file_path : %s", file)
                os.remove(file)

            ret = {'ret':'success'}
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
        
        watch_upload_path = ''
        watch_download_path = ''

        watch_upload_path = ModelSetting.get('watch_upload_path')
        watch_torrent_program = ModelSetting.get('watch_torrent_program')
        
        if watch_torrent_program == '0':
            watch_download_path = ModelSetting.get('transmission_default_path')
        elif watch_torrent_program == '1':
            watch_download_path = ModelSetting.get('downloadstation_default_path')
        elif watch_torrent_program == '2':
            watch_download_path = ModelSetting.get('qbittorrnet_default_path')
        elif watch_torrent_program == '3':
            watch_download_path = ModelSetting.get('aria2_default_path')
        
        if watch_upload_path != '' and watch_download_path != '':
            if watch_upload_path.rfind("/")+1 != len(watch_upload_path):
                watch_upload_path = watch_upload_path+'/'

            fileList = os.listdir(watch_upload_path)
            for file in fileList:
                if file.upper().find(".TORRENT") > -1:
                    magnet = LogicWatch.make_magnet_from_file(watch_upload_path+file)
                    logger.debug("search_from_torrent_file() magnet : %s", magnet)

                    
                    LogicNormal.add_download2(magnet, watch_torrent_program, watch_download_path, request_type='.torrent', request_sub_type='.torrent')
                    #완료 된 경우 삭제 or 파일명 변환
                    torrent_delete_yn = ModelSetting.get("torrent_delete_yn")

                    if torrent_delete_yn == 'True':
                        logger.debug("torrent_delete_yn : %s", torrent_delete_yn)
                        logger.debug("delete torrent file : %s", watch_upload_path+file)
                        os.remove(watch_upload_path+file)
                    else:
                        after_name = file.replace(".torrent", ".complete", 1).replace(".TORRENT", ".complete", 1)
                        logger.debug("before name : %s, after name : %s", file, after_name)
                        #파일 이동
                        shutil.move(watch_upload_path+file, watch_upload_path+after_name)
        else:
            logger.debug("watch_upload_path or watch_download_path Empty")
        logger.debug("finish watch folder searching...")

    @staticmethod
    def make_magnet_from_file(file):
        torrent = open(file, 'r').read()
        metadata = bencode.bdecode(torrent)

        hashcontents = bencode.bencode(metadata['info'])
        digest = hashlib.sha1(hashcontents).digest()
        b32hash = base64.b32encode(digest)

        params = {'xt': 'urn:btih:%s' % b32hash, 'dn': metadata['info']['name'], 'tr': metadata['announce'], 'xl': metadata['info']['length']}

        announcestr = ''
        for announce in metadata['announce-list']:
            announcestr += '&' + urllib.urlencode({'tr':announce[0]})

        paramstr = urllib.urlencode(params) + announcestr
        magneturi = 'magnet:?%s' % paramstr
        magneturi = magneturi.replace('xt=urn%3Abtih%3A', 'xt=urn:btih:', 1)
        return magneturi