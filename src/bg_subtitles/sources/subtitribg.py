# -*- coding: utf-8 -*-

from .nsub import log_my, savetofile, list_key
from .common import *
import requests
import re
try:
  import urllib.request
except:
  pass
import json
import io
import re
import requests

s = requests.Session()

values = {'s': ''}

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36'}

url = 'subtitri.bg'
url_full = 'https://subtitri.bg'

def get_id_url_n(txt, list):
    data = txt.replace('\t','').replace('\n','').replace('\r','')

    match = re.compile('<div class="featured-image".+?<a href="(.+?)".+?aria-label="(.+?)"').findall(data)
    for link, title in match:
        try:
            r = s.get(link, headers=headers)
            data_sub = r.text
            data_sub = data_sub.replace('\t', '').replace('\n', '').replace('\r', '')

            match_zip = re.search('epcl-download".+?<a href="(.+?)"', data_sub)

            if match_zip:
                ziplink = match_zip.group(1)

                tempurl = ziplink.encode('utf-8', 'replace').decode('utf-8')

                info = title.replace('&#8211;', '-')
                list.append({'url': tempurl,
                          'FSrc': '[COLOR CC00FF00][B][I](subtitribg) [/I][/B][/COLOR]',
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

def read_sub (mov):
  list = []
  log_my(mov)

  values['s'] = mov

  try:
      enc_values = urllib.parse.urlencode(values)
  except:
      enc_values = urllib.urlencode(values)
  
  log_my('Url: ', (url), 'Headers: ', (headers), 'Values: ', (enc_values))

  try:
    search_url = url_full+"/?"+enc_values
    matchSerial = re.search(r'S(\d+)E(\d+)', search_url, re.IGNORECASE)

    if matchSerial:
        search_url = re.sub(r's(\d+)e(\d+)', r'\1×\2', search_url, flags=re.IGNORECASE)
    else:
        pass

    r = s.get(search_url, headers=headers)
    data = r.text
  except:
    return None

  get_id_url_n(data, list)
  if run_from_xbmc == False:
    for k in list_key:
      d = get_data(list, k)
      log_my(d)

  return list

def get_sub(id, sub_url, filename):
  s = {}

  matchname = sub_url.split('/')

  link = sub_url

  r = requests.get(link)

  data = r.content

  s['data'] = data
  s['fname'] = matchname[len(matchname)-1]
  return s