# -*- coding: utf-8 -*-

from .nsub import log_my, savetofile, list_key
from .common import *
import re
try:
  import urllib.request
except Exception:
  pass
import json
import io
import gzip
import zlib
import http.client as http_client

values = {'movie':'',
          'act':'search',
          'select-language':'2',
          'upldr':'',
          'yr':'',
          'release':''}

head = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
           "Content-type": "application/x-www-form-urlencoded",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           # Prefer gzip (avoid brotli dependency/edge cases)
           "Accept-Encoding": "gzip, deflate",
           "Referer":"https://subs.sab.bz/index.php?",
           "Host":"subs.sab.bz",
           "Accept-Language":"en-US,en;q=0.5",
           # Reduce keep-alive surprises from the origin/CDN
           "Connection": "close",
           "Origin": "https://subs.sab.bz",
           "Pragma": "no-cache",
           "Cache-Control": "no-cache",
           }

url = "subs.sab.bz"
clean_str = r"(ddri\S*?'|','\#\S+\)|<div.*?>|<\/div>|<span.*?>|<\/span>|<img.*?\/>|<a[\s\S]*?>|<\/a>|<\/?b>|<br\s?\/>|&lt;b&gt;|\&\S*?;|\/[ab]|br\s\/|a\shref.*?_blank)|<\/?i>|<\/?font.*?>"
def get_id_url_n(txt, list):
  soup = BeautifulSoup(txt, 'html.parser')
  for link in soup.find_all('a', href=re.compile(r'[\S]attach_id=(?:\d+)')):
    p = link.find_parent('td')
    t = p.find_next_siblings('td', text=True)
    y = p.get_text()
    if y:
      yr = y.split('(')[1].split(')')[0]
    else:
      yr = 'n/s'
    try:
        f_info = re.sub(clean_str, " ", str(link.get('onmouseover').encode('utf-8', 'replace').decode('utf-8')))
        s_info = '#' + f_info + '#'
        t_info = re.search(r'Доп\. инфо(.+?)#', s_info)

        film_name = re.search(r'<b>(.+?)</b>', str(link.get('onmouseover').encode('utf-8', 'replace').decode('utf-8')))
        film_year = re.search(r'tooltip_year.+?(\(\d\d\d\d\))</span>', str(link.get('onmouseover').encode('utf-8', 'replace').decode('utf-8')))

        if film_name:
            check_name = film_name.group(1).replace("\\'", "'")
            if film_year:
                check_name = check_name + ' ' + film_year.group(1)
            else:
                pass
        else:
            check_name = ''
        if t_info:
            fo_info = '#' + re.sub(r'[а-яА-Я,!:;\\¤•-]|<u>|<\/?u>', '', str(t_info.group(1))) + '#'
            fo_info = fo_info.replace('  ', ' ').replace(' ', '.').replace('ETle™','')
            fo_info = fo_info.replace('..', '.').replace('..', '.').replace('..', '.').replace('..', '.').replace('..','.').replace('..', '.').replace('..', '.').replace('#.', '#').replace('#*', '').replace('*', '\n').replace('.#','').replace(':.', ':').replace('#', '\n')
            fo_info = re.sub(r'\:.+?\:', '', fo_info)
            fo_info = re.sub(r'\:.+?\.', '', fo_info)
            if check_name != '':
                fo_info = check_name + fo_info
            else:
                pass
        else:
            fo_info = f_info
        # Attempt to capture DL and comments if columns are present
        try:
            dl = t[4].string.encode('utf-8', 'replace').decode('utf-8') if len(t) > 4 else ''
        except Exception:
            dl = ''
        try:
            kom = t[5].string.encode('utf-8', 'replace').decode('utf-8') if len(t) > 5 else ''
        except Exception:
            kom = ''
        list.append({'url': link['href'].split('attach_id=')[1],
                    'FSrc': '[COLOR CC00FF00][B][I](subsab) [/I][/B][/COLOR]',
                    'info': fo_info,
                    'year': yr,
                    'cds': t[2].string.encode('utf-8', 'replace').decode('utf-8'),
                    'fps': t[3].string.encode('utf-8', 'replace').decode('utf-8'),
                    'downloads': dl,
                    'comments': kom,
                    'rating': re.search('alt="Rating:(.+?)"', str(link.find_parent('tr'))).group(1).strip(),
                    'id': __name__})
    except:
        try:
            dl2 = t[4].string.encode('utf-8', 'replace') if len(t) > 4 else b''
        except Exception:
            dl2 = b''
        try:
            kom2 = t[5].string.encode('utf-8', 'replace') if len(t) > 5 else b''
        except Exception:
            kom2 = b''
        list.append({'url': link['href'].split('attach_id=')[1],
                    'FSrc': '[COLOR CC00FF00][B][I](subsab) [/I][/B][/COLOR]',
                    'info': re.sub(clean_str, " ", link.get('onmouseover').encode('utf-8', 'replace')),
                    'year': yr,
                    'cds': t[2].string.encode('utf-8', 'replace'),
                    'fps': t[3].string.encode('utf-8', 'replace'),
                    'downloads': dl2,
                    'comments': kom2,
                    'rating': re.search('alt="Rating:(.+?)"', str(link.find_parent('tr'))).group(1).strip(),
                    'id': __name__})

  return

def get_data(l, key):
  out = []
  for d in l:
    out.append(d[key])
  return out

def _https_request(method: str, path: str, body: bytes | None, headers: dict):
  """Do a single HTTPS request with minimal redirect + gzip handling."""
  conn = http_client.HTTPSConnection(url, timeout=12)
  try:
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    # Follow one redirect if needed
    if resp.status in (301, 302, 303, 307, 308):
      loc = resp.getheader('Location') or ''
      conn.close()
      if loc:
        # Normalize to path-only for the same host
        try:
          from urllib.parse import urlparse
          p = urlparse(loc)
          path2 = p.path or '/'
          if p.query:
            path2 += '?' + p.query
          conn2 = http_client.HTTPSConnection(url, timeout=12)
          conn2.request('GET', path2, headers=headers)
          return conn2.getresponse(), conn2
        except Exception:
          # Fall through to original response
          pass
    return resp, conn
  except Exception:
    try:
      conn.close()
    except Exception:
      pass
    raise


def _read_body(resp) -> bytes:
  enc = (resp.getheader('Content-Encoding') or '').lower()
  raw = resp.read()
  if 'gzip' in enc:
    try:
      return gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    except Exception:
      return raw
  if 'deflate' in enc:
    try:
      # Try raw DEFLATE (RFC1951)
      return zlib.decompress(raw, -zlib.MAX_WBITS)
    except Exception:
      try:
        # Try zlib-wrapped (RFC1950)
        return zlib.decompress(raw)
      except Exception:
        return raw
  return raw


def _http_request(method: str, path: str, body: bytes | None, headers: dict):
  """Plain HTTP fallback in case HTTPS repeatedly fails (edge/CDN quirk)."""
  conn = http_client.HTTPConnection(url, timeout=12)
  try:
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    return resp, conn
  except Exception:
    try:
      conn.close()
    except Exception:
      pass
    raise


def read_sub(mov, year, normalized_fragment=None):
  list = []
  log_my(mov, year)

  values['movie'] = mov
  values['yr'] = year

  try:
      enc_values = urllib.parse.urlencode(values).encode("utf-8")
  except Exception:
      enc_values = urllib.urlencode(values)  # type: ignore[attr-defined]
      if isinstance(enc_values, str):
        enc_values = enc_values.encode('utf-8')
  log_my('Url: ', (url), 'Headers: ', (head), 'Values: ', (enc_values))

  # Primary attempt over HTTP (SAB HTTPS often refuses), fallback to HTTPS if HTTP fails.
  for attempt in (1, 2, 3):
    try:
      response, conn = _http_request("POST", "/index.php?", enc_values, head)
      ctype = (response.getheader('content-type') or '').split(';')[0]
      if response.status != 200 or ctype != 'text/html':
        try:
          conn.close()
        except Exception:
          pass
        if attempt < 3:
          import time as _t
          _t.sleep(0.4 * attempt)
          continue
        # HTTP failed; try HTTPS once before giving up
        response, conn = _https_request("POST", "/index.php?", enc_values, head)
        ctype = (response.getheader('content-type') or '').split(';')[0]
        if response.status != 200 or ctype != 'text/html':
          try:
            conn.close()
          except Exception:
            pass
          return None
      try:
        headers_dump = response.getheaders()
        log_my(headers_dump)
      except Exception:
        pass
      try:
        data = _read_body(response)
      except Exception as exc:
        log_my('subs_sab.read_sub body error', exc)
        try:
          conn.close()
        except Exception:
          pass
        if attempt < 3:
          import time as _t
          _t.sleep(0.4 * attempt)
          continue
        return None
      try:
        conn.close()
      except Exception:
        pass
      break
    except Exception as exc:
      log_my('subs_sab.read_sub connection error', exc)
      if attempt < 3:
        import time as _t
        _t.sleep(0.4 * attempt)
        continue
      # Final fallback: try HTTPS once more
      try:
        response, conn = _https_request("POST", "/index.php?", enc_values, head)
        ctype = (response.getheader('content-type') or '').split(';')[0]
        if response.status != 200 or ctype != 'text/html':
          try:
            conn.close()
          except Exception:
            pass
          return None
        headers_dump = response.getheaders()
        log_my(headers_dump)
        data = _read_body(response)
        try:
          conn.close()
        except Exception:
          pass
        break
      except Exception:
        return None

  get_id_url_n(data, list)
  if run_from_xbmc == False:
    for k in list_key:
      d = get_data(list, k)
      log_my(d)

  return list

def get_sub(id, sub_url, filename):
  s = {}
  path = f"/index.php?act=download&attach_id={sub_url}"
  for attempt in (1, 2, 3):
    try:
      # Try HTTPS first (downloads often require TLS), then fall back to HTTP once.
      response, conn = _https_request("GET", path, None, head)
      if response.status != 200:
        try:
          conn.close()
        except Exception:
          pass
        if attempt < 3:
          import time as _t
          _t.sleep(0.3 * attempt)
          continue
        return None
      try:
        s['data'] = _read_body(response)
      except Exception as exc:
        log_my('subs_sab.get_sub body error', exc)
        try:
          conn.close()
        except Exception:
          pass
        if attempt < 3:
          import time as _t
          _t.sleep(0.3 * attempt)
          continue
        return None
      try:
        disp = response.getheader('Content-Disposition') or ''
        fname = disp.split('filename=')[1].strip('"') if 'filename=' in disp else 'subtitle.srt'
      except Exception:
        fname = 'subtitle.srt'
      s['fname'] = fname
      try:
        conn.close()
      except Exception:
        pass
      break
    except Exception as exc:
      log_my('subs_sab.get_sub connection error', exc)
      if attempt < 3:
        import time as _t
        _t.sleep(0.3 * attempt)
        continue
      # Fallback to HTTP once
      try:
        response, conn = _http_request("GET", path, None, head)
        if response.status != 200:
          try:
            conn.close()
          except Exception:
            pass
          return None
        s['data'] = _read_body(response)
        try:
          disp = response.getheader('Content-Disposition') or ''
          fname = disp.split('filename=')[1].strip('"') if 'filename=' in disp else 'subtitle.srt'
        except Exception:
          fname = 'subtitle.srt'
        s['fname'] = fname
        try:
          conn.close()
        except Exception:
          pass
        break
      except Exception:
        return None
  return s
