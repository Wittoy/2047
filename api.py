import re
import time

from constants import *

# json apis sharing a common endpoint

api_registry = {}
def register(name):
    def k(f):
        api_registry[name] = f
    return k

@register('test')
def _(j):
    # raise Exception('ouch')
    return {'double':int(j['a'])*2}

@register('login')
def _(j):
    def k(s): return j[s]
    uname = k('username')
    pwh = k('password_hash')

    # find user
    u = aql('for u in users filter u.name==@n return u', n=uname)

    if len(u)==0:
        raise Exception('username not found')

    u = u[0]

    # find password object
    p = aql('for p in passwords filter p.uid==@uid return p', uid=u['uid'])
    if len(p)==0:
        raise Exception('password record for the user not found')

    p = p[0]
    hashstr = p['hashstr']
    saltstr = p['saltstr']

    # hash incoming with salt and check
    verified = check_hash_salt_pw(hashstr, saltstr, pwh)

    if not verified:
        raise Exception('wrong password')

    return {'error':False, 'message':'login success', 'setuid':u['uid']}

@register('register')
def _(j):
    def k(s): return j[s]

    uname = k('username')
    pwh = k('password_hash')
    ik = k('invitation_code')

    # check if user name is legal
    m = re.fullmatch(username_regex, uname)
    if m is None:
        raise Exception('username doesnt match requirement')

    # check if username occupied
    if len(aql('for u in users filter u.name==@n return 1',n=uname))>0:
        raise Exception('username occupied')

    # assert len(pwh) == 32 # sanity

    # check if invitation code exist and valid
    invitation = aql('''
        for i in invitations
        filter i._key == @ik and i.active != false return i
    ''',ik=ik)

    if len(invitation) == 0:
        raise Exception('invitation code not exist or expired')

    # generate salt, hash the pw
    hashstr, saltstr = hash_w_salt(pwh)

    # obtain a new uid
    uid = aql('''
        let c = document('counters/counters')
        update c with {uid:c.uid+1} in counters return NEW.uid
    ''')[0]

    newuser = dict(
        uid=uid,
        name=uname,
        t_c=time_iso_now(),
        brief='',
        invitation=ik,
    )

    pwobj = dict(
        uid=uid,
        hashstr=hashstr,
        saltstr=saltstr,
    )

    aql('''insert @i into users''', i=newuser)
    aql('''insert @i into passwords''', i=pwobj)

    aql('''for i in invitations filter i._key==@ik
        update i with {active:false} in invitations''', ik=ik)

    return newuser

@register('logout')
def _(j):
    return {'logout':True}

def content_length_check(content, allow_short=False):
    if len(content)>100000:
        raise Exception('content too long')
    if len(content)<4 and allow_short==False:
        raise Exception('content too short')

@register('post')
def _(j):
    if 'logged_in' not in j:
        raise Exception('you are not logged in')

    uid = j['logged_in']['uid']

    def es(k): return (str(j[k]) if (k in j) else None)

    target_type = es('type')
    # pid = int(es('pid'))
    id = int(es('id'))

    # title = es('title').strip()

    content = es('content').strip()
    content_length_check(content)

    if target_type=='thread':
        # check if tid exists
        tid = id

        thread = aql('for t in threads filter t.tid==@k return t',k=tid,silent=True)
        if len(thread)==0:
            raise Exception('tid not exist')

        thread = thread[0]

        # check if user repeatedly submitted the same content
        lp = aql('for p in posts filter p.uid==@k sort p.t_c desc limit 1 return p',k=uid, silent=True)
        if len(lp) == 1:
            if lp[0]['content'] == content:
                raise Exception('repeatedly posting same content')

        timenow = time_iso_now()

        newpost = dict(
            uid=uid,
            t_c=timenow,
            content=content.strip(),
            tid=tid,
        )
        inserted = aql('insert @p in posts return NEW', p=newpost)[0]

        # update thread update time
        aql('''
        for t in threads filter t.tid==@tid
        update t with {t_u:@now} in threads
        ''',silent=True,tid=tid,now=timenow)

        return inserted

    else:
        raise Exception('unsupported type:'+target_type)

@register('render')
def _(j):
    if 'logged_in' not in j: raise Exception('you are not logged in')

    def es(k): return (str(j[k]) if (k in j) else None)

    content = es('content').strip()
    content_length_check(content, allow_short=True)

    return {'html':convert_markdown(content)}

import os, base64
def r8():return os.urandom(8)

@register('generate_invitation_code')
def _(j):
    if 'logged_in' not in j: raise Exception('you are not logged in')
    uid = j['logged_in']['uid']

    invs = aql('''for i in invitations
        filter i.uid==@k and i.active == true
        return i''',
        k=uid, silent=True)

    if len(invs)>=5:
        raise Exception('you can only generate so much invitation code')

    code = '2047'+base64.b16encode(r8()).decode('ascii')

    inv = dict(
        active=True,
        uid=uid,
        _key=code,
        t_c=time_iso_now(),
    )

    aql('insert @k in invitations', k=inv)

    return {'error':False}

# feedback regulated ping service
# average 1 ping every 3 sec
lastping = time.time()
pingtime = 1.
durbuf = 0
@register('ping')
def _(args):
    global lastping,durbuf,pingtime
    now = time.time()
    dur = now - lastping

    durbuf = dur*0.1+durbuf*0.9
    lastping = now
    target = 3
    err = target - dur

    pingtime = max(1, pingtime + err * 0.3)
    # print('==={:4.4f}'.format(durbuf), 'pingtime {:4.4f}'.format(pingtime))
    ping_itvl = int(pingtime*1000)
    return {'ping':'pong','interval':ping_itvl}