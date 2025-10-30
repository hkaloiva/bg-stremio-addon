# -*- coding: utf-8 -*-

from .nsub import log_my, savetofile, list_key
from .common import *
import json
import io
import ssl
import gzip
from urllib import request as urllib_request, parse as urllib_parse, error as urllib_error

values = {'m':'',
          'a':'',
          't':'Submit',
          'g':'',
          'u':'',
          'action':'????',
          'y':'',
          'c':'',
          'l':'0',
          'd':''}

headers = {
            "Host": "subsunacs.net",
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:52.0) Gecko/20100101 Firefox/52.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
          }

url = 'https://subsunacs.net'
clean_str = r"(<div.*?>|<\/div>|<span.*?>|<\/span>|<img.*?>|<a[\s\S]*?>|<\/a>|<\/?b>|<br\s?\/>|<br>|\&\S*?;|<\/?u>|<\/?strong>|<\/?em>)"
_UNVERIFIED_CTX = ssl._create_unverified_context()


def _open_request(req: urllib_request.Request):
  """Open request with relaxed SSL verification for subsunacs.net."""
  return urllib_request.urlopen(req, context=_UNVERIFIED_CTX)

def _dedupe_entries(entries):
  seen = set()
  deduped = []
  for entry in entries:
    url_key = entry.get('url')
    if url_key and url_key in seen:
      continue
    if url_key:
      seen.add(url_key)
    deduped.append(entry)
  return deduped

def get_id_url_n(txt, list):
  soup = BeautifulSoup(txt, 'html.parser')
  # dump_src(soup, 'src.html')
  for link in soup.find_all('a', href=re.compile(r'(?:\/subtitles\/\w+.*\/$)')):
    t = link.find_parent('td').find_next_siblings('td')
    y = link.find_next_sibling('span', text=True)
    if y:
      yr = y.get_text().split('(')[1].split(')')[0]
    else:
      yr = 'n/s'
    
    try:
        f_info = re.sub(clean_str, " ", str(link.get('title').encode('utf-8', 'replace').decode('utf-8')))
        s_info = f_info + '#'
        t_info = re.search('Инфо: (.+?)#', s_info)
        film_name = re.search(r'Филм:(.+?)Формат', s_info)

        if film_name:
            check_name = '#' + film_name.group(1)
            check_name = check_name.replace('# ', '')
            check_name = re.sub(clean_str, "", check_name)
        else:
            check_name = ''
        if t_info:
            fo_info = '#' + re.sub(r'[а-яА-Я,!:;\\/¤•-]|<u>|<\/?u>', '', str(t_info.group(1)))
            fo_info = fo_info.replace('  ', ' ').replace(' ', '.').replace('ETle™','')
            fo_info = fo_info.replace('..', '.').replace('..', '.').replace('..', '.').replace('..', '.').replace('..','.').replace('..', '.').replace('..', '.').replace('#.', '#').replace('#*', '').replace('*', '\n').replace('.#','').replace('#', '\n')
            if check_name != '':
                fo_info = check_name + fo_info
            else:
                pass
        else:
            fo_info = f_info
        list.append({'url': link['href'],
                  'FSrc': '[COLOR CC00FF00][B][I](subsunacs) [/I][/B][/COLOR]',
                  'info': fo_info,
                  'year': yr,
                  'cds': t[0].string.encode('utf-8', 'replace').decode('utf-8'),
                  'fps': t[1].string.encode('utf-8', 'replace').decode('utf-8'),
                  'rating': t[2].a.img and t[2].a.img.get('alt') or '0.0',
                  'id': __name__})
    except:
        list.append({'url': link['href'],
                  'FSrc': '[COLOR CC00FF00][B][I](subsunacs) [/I][/B][/COLOR]',
                  'info': re.sub(clean_str, " ", link.get('title').encode('utf-8', 'replace')),
                  'year': yr,
                  'cds': t[0].string.encode('utf-8', 'replace'),
                  'fps': t[1].string.encode('utf-8', 'replace'),
                  'rating': t[2].a.img and t[2].a.img.get('alt') or '0.0',
                  'id': __name__})
  return

def get_data(l, key):
  out = []
  for d in l:
    out.append(d[key])
  return out

def read_sub (mov, year):
  list = []
  log_my(mov, year)

  values['m'] = mov
  values['y'] = year
  
  try:
      enc_values = urllib_parse.urlencode(values).encode("utf-8")
  except Exception:  # noqa: BLE001
      enc_values = urllib_parse.urlencode(values)
      if isinstance(enc_values, str):
          enc_values = enc_values.encode("utf-8")
  log_my('Url: ', (url), 'Headers: ', (headers), 'Values: ', (enc_values))

  try:
      request = urllib_request.Request(url + '/search.php', enc_values, headers)
      response = _open_request(request)
  except urllib_error.URLError as exc:
      log_my('subsunacs.read_sub urlopen error', exc)
      return None
      
  try:
    code = getattr(response, "status", None) or response.getcode()
    log_my(code, BaseHTTPServer.BaseHTTPRequestHandler.responses[code][0])
  except Exception:
    pass

  if response.info().get('Content-Encoding') == 'gzip':
    try:
        buf = StringIO(response.read())
    except:
        buf = io.BytesIO(response.read())
    f = gzip.GzipFile(fileobj=buf)
    data = f.read()
    f.close()
    buf.close()
  else:
    log_my('Error: ', response.info().get('Content-Encoding'))
    return None

  get_id_url_n(data, list)
  list[:] = _dedupe_entries(list)
  if run_from_xbmc == False:
    for k in list_key:
      d = get_data(list, k)
      log_my(d)

  return list

def get_sub(id, sub_url, filename):
  s = {}
  try:
      enc_values = urllib_parse.urlencode(values).encode("utf-8")
  except Exception:  # noqa: BLE001
      enc_values = urllib_parse.urlencode(values)
      if isinstance(enc_values, str):
          enc_values = enc_values.encode("utf-8")
  headers['Referer'] = url + '/search.php?'
  try:
      request = urllib_request.Request(url + sub_url, enc_values, headers)
      response = _open_request(request)
      s['data'] = response.read()
      s['fname'] = response.info()['Content-Disposition'].split('filename=')[1].strip('"')
  except urllib_error.URLError as exc:
      log_my('subsunacs.get_sub urlopen error', exc)
      return {}
  return s
