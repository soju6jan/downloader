# -*- coding: utf-8 -*-
#########################################################
# python
import traceback
from datetime import datetime
import json
import os

# third-party
from sqlalchemy import or_, and_, func, not_, desc
from sqlalchemy.orm import backref

# sjva 공용
from framework import app, db, path_app_root
from framework.util import Util

# 패키지
from .plugin import logger, package_name

app.config['SQLALCHEMY_BINDS'][package_name] = 'sqlite:///%s' % (os.path.join(path_app_root, 'data', 'db', '%s.db' % package_name))
#########################################################
        
class ModelSetting(db.Model):
    __tablename__ = '%s_setting' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String, nullable=False)
 
    def __init__(self, key, value):
        self.key = key
        self.value = value

    def __repr__(self):
        return repr(self.as_dict())

    def as_dict(self):
        return {x.name: getattr(self, x.name) for x in self.__table__.columns}

    @staticmethod
    def get(key):
        try:
            return db.session.query(ModelSetting).filter_by(key=key).first().value.strip()
        except Exception as e:
            logger.error('Exception:%s %s', e, key)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def get_int(key):
        try:
            return int(ModelSetting.get(key))
        except Exception as e:
            logger.error('Exception:%s %s', e, key)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def get_bool(key):
        try:
            return (ModelSetting.get(key) == 'True')
        except Exception as e:
            logger.error('Exception:%s %s', e, key)
            logger.error(traceback.format_exc())

    @staticmethod
    def set(key, value):
        try:
            item = db.session.query(ModelSetting).filter_by(key=key).with_for_update().first()
            if item is not None:
                item.value = value.strip()
                db.session.commit()
            else:
                db.session.add(ModelSetting(key, value.strip()))
        except Exception as e:
            logger.error('Exception:%s %s', e, key)
            logger.error(traceback.format_exc())

    @staticmethod
    def to_dict():
        try:
            from framework.util import Util
            ret = Util.db_list_to_dict(db.session.query(ModelSetting).all())
            ret['package_name'] = package_name
            return ret
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def setting_save(req):
        try:
            for key, value in req.form.items():
                if key in ['scheduler', 'is_running']:
                    continue
                if key.startswith('tmp_'):
                    continue
                logger.debug('Key:%s Value:%s', key, value)
                entity = db.session.query(ModelSetting).filter_by(key=key).with_for_update().first()
                entity.value = value
            db.session.commit()
            return True                  
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            logger.debug('Error Key:%s Value:%s', key, value)
            return False

    @staticmethod
    def get_list(key):
        try:
            value = ModelSetting.get(key)
            values = [x.strip().replace(' ', '').strip() for x in value.replace('\n', '|').split('|')]
            values = Util.get_list_except_empty(values)
            return values
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            logger.error('Error Key:%s Value:%s', key, value)




class ModelDownloaderItem(db.Model):
    __tablename__ = 'plugin_%s_item' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime)
    request_type = db.Column(db.String)
    request_sub_type = db.Column(db.String)

    title = db.Column(db.String)
    download_url = db.Column(db.String)
    download_path = db.Column(db.String)
    torrent_program = db.Column(db.String)
    program_id = db.Column(db.String)
    status = db.Column(db.String)
    completed_time = db.Column(db.DateTime)
    #ktv = db.relationship('ModelDownloaderKtv', backref='downloader_item', lazy=True)
    #download_timeda = db.Column(db.Integer)

    def __init__(self, request_type, request_sub_type, download_url, download_path, torrent_program):
        self.request_type = request_type #web, rss, tv, movie
        self.request_sub_type = request_sub_type
        self.download_url = download_url.split('&')[0]
        self.download_path = download_path
        self.torrent_program = torrent_program
        self.program_id = ''
        self.created_time = datetime.now()
        self.status = 'request'
        self.title = ''
        #self.completed_time = ''

    def __repr__(self):
        return repr(self.as_dict())

    def as_dict(self):
        ret = {x.name: getattr(self, x.name) for x in self.__table__.columns}
        ret['created_time'] = self.created_time.strftime('%m-%d %H:%M:%S') 
        if ret['completed_time'] is not None and ret['completed_time'] != '':
            ret['completed_time'] = self.completed_time.strftime('%m-%d %H:%M:%S')
            tmp = (self.completed_time - self.created_time).seconds
            ret['timedelta'] = '%s분 %s초' % ((tmp/60), (tmp%60))
        else:
            ret['completed_time'] = ''
            ret['timedelta'] = ''

        return ret
    
    @staticmethod
    def save(data, request_type, request_sub_type):
        try:
            if data['ret'] == 'success':
                item = ModelDownloaderItem(request_type, request_sub_type, data['download_url'], data['download_path'], data['default_torrent_program'])
                db.session.add(item)
                db.session.commit()
                return item.id
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def web_list(req):
        try:
            ret = {}
            page = 1
            page_size = ModelSetting.get_int('web_page_size')
            search = ''
            if 'page' in req.form:
                page = int(req.form['page'])
            if 'search_word' in req.form:
                search = req.form['search_word']
            request_type = req.form['request_type']
            program_type = req.form['program_type']
            order = req.form['order'] if 'order' in req.form else 'desc'

            query = ModelDownloaderItem.make_query(search=search, request_type=request_type, program_type=program_type, order=order)
            count = query.count()
            query = query.limit(page_size).offset((page-1)*page_size)
            logger.debug('ModelDownloaderItem count:%s', count)
            lists = query.all()
            ret['list'] = [item.as_dict() for item in lists]
            ret['paging'] = Util.get_paging_info(count, page, page_size)
            return ret
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def make_query(search='', request_type='all', program_type='all', order='desc'):
        query = db.session.query(ModelDownloaderItem)
        if search is not None and search != '':
            if search.find('|') != -1:
                tmp = search.split('|')
                conditions = []
                for tt in tmp:
                    if tt != '':
                        conditions.append(ModelDownloaderItem.title.like('%'+tt.strip()+'%') )
                query = query.filter(or_(*conditions))
            elif search.find(',') != -1:
                tmp = search.split(',')
                for tt in tmp:
                    if tt != '':
                        query = query.filter(ModelDownloaderItem.title.like('%'+tt.strip()+'%'))
            else:
                query = query.filter(ModelDownloaderItem.title.like('%'+search+'%'))

        
        if request_type != 'all':
            query = query.filter(ModelDownloaderItem.request_type == request_type)
        if program_type != 'all':
            query = query.filter(ModelDownloaderItem.torrent_program == program_type)
        if order == 'desc':
            query = query.order_by(desc(ModelDownloaderItem.id))
        else:
            query = query.order_by(ModelDownloaderItem.id)

        return query