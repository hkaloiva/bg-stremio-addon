# -*- coding: utf-8 -*-

from .nsub import log_my, savetofile, list_key
from .common import *
import io
import json
import re
from urllib.parse import unquote
try:
  import urllib.request
except:
  pass
import requests

s = requests.Session()
REQUEST_TIMEOUT = 8

values = {'q': ''}

url = 'vladoon.mooo.com'
url_full = 'https://vladoon.mooo.com/subs/'

headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            'accept': 'application/json'
}

FILENAME_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.IGNORECASE)


def _resolve_filename(response, fallback):
  disposition = response.headers.get('content-disposition') or ''
  match = FILENAME_RE.search(disposition)
  if match:
    candidate = unquote(match.group(1).strip().strip('"'))
    if candidate:
      return candidate
  return fallback


def get_id_url_n(txt, list):
    data = txt.replace('\t','').replace('\n','').replace('\r','')
    match = re.compile(r'"id":(.+?),.+?"original_title":"(.+?)",.+?"release_names":\[(.+?)\],').findall(data)

    for link, title, release in match:
        try:
            tempurl = url_full + 'download/' + link
            info = title + ' / ' + release.replace('"','')

            list.append({'url': tempurl,
                      'FSrc': '[COLOR CC00FF00][B][I](Vlad00n) [/I][/B][/COLOR]',
                      'info': info.encode('utf-8', 'replace').decode('utf-8'),
                      'year': '',
                      'cds': '',
                      'fps': '',
                      'rating': '0.0',
                      'id': __name__})
        except:
            pass
    else:
        pass
    return

def get_data(l, key):
  out = []
  for d in l:
    out.append(d[key])
  return out

def _filter_results(results, query, year_hint):
  if not results:
    return results

  tokens = [token for token in re.split(r"[^a-z0-9]+", query.lower()) if token]
  year_token = year_hint if year_hint and year_hint.isdigit() else ""

  if not tokens and not year_token:
    return results

  filtered = []
  for entry in results:
    info_norm = " ".join(re.split(r"[^a-z0-9]+", str(entry.get('info') or '').lower()))
    if tokens and not all(token in info_norm for token in tokens):
      continue
    if year_token and year_token not in info_norm:
      continue
    filtered.append(entry)

  if filtered:
    return filtered

  if year_token:
    loose = [entry for entry in results if year_token in str(entry.get('info') or '')]
    if loose:
      return loose

  return results


def read_sub (mov, year_hint=""):
  list = []
  log_my(mov)

  values['q'] = mov

  try:
      enc_values = urllib.parse.urlencode(values)
  except:
      enc_values = urllib.urlencode(values)
  
  log_my('Url: ', (url), 'Headers: ', (headers), 'Values: ', (enc_values))

  try:
    search_url = url_full+"search-subtitles?"+enc_values.replace('+', ' ')
    #matchSerial = re.search(r'S(\d+)E(\d+)', search_url, re.IGNORECASE)

    #if matchSerial:
    #    search_url = re.sub(r's(\d+)e(\d+)', r'\1×\2', search_url, flags=re.IGNORECASE)
    #else:
    #    pass

    r = s.get(search_url, headers=headers, timeout=REQUEST_TIMEOUT)
    data = str(r.text)
  except:
    return None

  get_id_url_n(data, list)
  list = _filter_results(list, mov, year_hint)
  if run_from_xbmc == False:
    for k in list_key:
      d = get_data(list, k)
      log_my(d)

  return list

def get_sub(id, sub_url, filename):
  s = {}

  matchname = sub_url.split('/')

  link = sub_url

  r = requests.get(link, timeout=REQUEST_TIMEOUT)

  data = r.content
  filename = _resolve_filename(r, matchname[len(matchname)-1])

  s['data'] = data
  s['fname'] = filename
  return s
