import aiohttp
import asyncio
import aioredis
from pathlib import Path
from datetime import datetime, timedelta

import aiomcache
from sanic import Sanic
from sanic.request import Request as _Request
from sanic.exceptions import NotFound
from sanic.response import HTTPResponse, text
from sanic_jwt import Initialize
from sanic_session import Session, MemcacheSessionInterface

import config
from ext import mako, init_db, sentry
from models.mc import cache
from models import jwt_authenticate, User
from models.var import redis_var, memcache_var

from werkzeug.utils import find_modules, import_string, ImportStringError


async def retrieve_user(request, payload, *args, **kwargs):
    if payload:
        user_id = payload.get('user_id', None)
        if user_id is None:
            return
        return await User.get_or_404(user_id)


async def store_refresh_token(user_id, refresh_token, *args, **kwargs):
    key = f'refresh_token_{user_id}'
    await redis.set(key, refresh_token)


async def retrieve_refresh_token(user_id, *args, **kwargs):
    key = f'refresh_token_{user_id}'
    return await redis.get(key)


def register_blueprint(root, app):
    for name in find_modules(root, recursive=True):
        mod = import_string(name)
        if hasattr(mod, 'bp'):
            if mod.bp.name == 'admin':
                Initialize(mod.bp, app=app, authenticate=jwt_authenticate,
                retrieve_user=retrieve_user,
                store_refresh_token=store_refresh_token,
                secret=config.JWT_SECRET,
                expiration_dela=config.EXPIRATION_DELA)
            app.register_blueprint(mod.bp)


class Request(_Request):
    user = None


app = Sanic(__name__, request_class=Request)
app.config.from_object(config)
mako.init_app(app, context_processors=())
if sentry is not None:
    sentry.init_app(app)
register_blueprint('views', app)
app.static('/static', './static')

session = Session()
client = None
redis = None


@app.exception(NotFound)
async def ignore_404s(request, exception):
    return text("Oops, page not found.")


async def server_error_handle(request, exception):
    return text("Oops, Sanic Server Error.", status=500)


app.listener('before_server_start')
async def setup_db(app, loop):
    