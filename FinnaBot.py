#!/usr/bin/env python

import twitter
import requests
from PIL import Image

import re
import os.path
import random
import urllib
import time
import StringIO
import logging

BOT_NAME='Finna Bot'
SCREEN_NAME='FinnaBot'

CREDENTIALS_FILE='~/.finnabot_credentials'
# App registered by @OsmaSuominen
# I don't care that these are public, as the real authentication is done using OAuth tokens
CONSUMER_KEY='NaVzkMJB0QXv9UWLkqYHXieXy'
CONSUMER_SECRET='DAzOoOkh06x3qzQGnFz9EUdrCHm7wY5lJrHrqXsoJChoPEumBC'

FINNA_API_SEARCH='https://api.finna.fi/v1/search'
FINNA_RECORD_URL='https://www.finna.fi/Record/'
FINNA_IMAGE_URL='https://api.finna.fi'

STATUS_MAXCOUNT=20 # maximum number of status messages to process per cycle
TWEET_MAXLENGTH=139 # maximum length of the text part, excluding image link
HASHTAG_BLACKLIST=['pinnalla','viraali','finland','mielipide','puheenvuoro']
HASHTAG_MINLENGTH=4
IMAGE_MINSIZE_BYTES=1024 # minimum size of image in bytes; smaller ones won't be tweeted
IMAGE_MAXSIZE_BYTES=1024*1024 # maximum size of image in bytes; larger images will be scaled down
IMAGE_MAXSIZE_SCALED=(1024,1024) # maximum size of scaled image in pixels

def transform_hit(hit):
    """transform a Finna hit into a simpler flat dict with the metadata we need"""
    data = {}
    if 'title' in hit:
        data['title'] = hit['title']
    if 'images' in hit:
        data['image'] = hit['images'][0]
    if 'nonPresenterAuthors' in hit:
        data['author'] = ', '.join(a['name'] for a in hit['nonPresenterAuthors'])
    if 'year' in hit:
        data['year'] = hit['year']
    data['building'] = ', '.join(b['translated'] for b in hit['buildings'])
    data['id'] = hit['id']
    return data
    
def validate_result(result):
    """make sure we have enough metadata to produce a sensible tweet, and avoid posting the same twice"""
    if 'image' not in result:
        return False
    if result['id'] in already_posted:
        return False
    return True

def search_finna(keyword):
    """search Finna using the given keyword and return a single, random result, or None if no results"""
    fields = ['title','images','nonPresenterAuthors','buildings','id','year']
    filters = ['format:0/Image/', 'online_boolean:1']
    params = {'filter[]': filters,'lookfor':keyword,'lng':'fi','limit':100,'field[]':fields}
    r = requests.get(FINNA_API_SEARCH, params=params, headers={'User-Agent': BOT_NAME})
    response = r.json()
    if 'records' in response:
        results = [transform_hit(hit) for hit in response['records']]
        validated_results = filter(validate_result, results)
        if len(validated_results) > 0:
            return random.choice(validated_results)
        else:
            return None
    else:
        return None

def hashtag_to_keyword(hashtag):
    """convert a hashtag into a (potentially multiple word) keyword for searching Finna"""
    # TODO split CamelCase into words
    return hashtag

def handle_hashtag(hashtag):
    """process a single hashtag, returning a result from Finna, or None"""
    if hashtag.lower() in HASHTAG_BLACKLIST or len(hashtag) < HASHTAG_MINLENGTH:
        # ignore blacklisted or too short hashtags
        return None
    keyword = hashtag_to_keyword(hashtag)
    return search_finna(keyword)

def author_statement(result):
    """return as much information as we have about author, year and building"""
# author disabled for now, because it takes so much space in the tweet
#
#    if 'author' in result and 'year' in result:
#        return "%s, %s. %s" % (result['author'], result['year'], result['building'])
#    if 'author' in result:
#        return "%s. %s" % (result['author'], result['building'])
    if 'year' in result:
        return "%s. %s" % (result['year'], result['building'])
    return result['building']

def shorten_title(title, maxlength):
    if title.endswith('.'):
        title = title[:-1] # remove trailing period
    if len(title) <= maxlength:
        # no need to shorten
        return title
    else:
        # need to shorten
        return title[:maxlength-2] + ".."

def compose_tweet(tag, result, reply_to_user):
    """compose a tweet based on a Finna result. Return the tweet text, or None if composing failed"""
    author_info = author_statement(result)
    url = FINNA_RECORD_URL + urllib.quote(result['id'])
    text = "%s %s #%s" % (author_info, url, tag)
    if reply_to_user is not None:
        prepend = '.@%s ' % reply_to_user
    else:
        prepend = ''
    if 'title' in result:
        length = len(prepend) + len(text) - len(url) + 23 # correct for t.co URL shortening
        shortened_title = shorten_title(result['title'], TWEET_MAXLENGTH-length-2)
        text = '%s. %s' % (shortened_title, text)

    text = prepend + text
    length = len(text) - len(url) + 23 # correct for URL shortening
    if length > TWEET_MAXLENGTH:
        return # failed creating a proper length tweet
    logging.debug("%d: %s", length, text)
    return text

def parse_tweet(tweet, reply=False):
    """parse a single incoming tweet, returning a (text, result) tuple"""
    if tweet['user']['screen_name'] == SCREEN_NAME:
        return None # ignore my own tweets
    logging.info("%s @%s: %s", tweet['created_at'], tweet['user']['screen_name'], tweet['text'])
    hashtags = [h['text'] for h in tweet['entities']['hashtags']]
    tag_results = {}
    for tag in hashtags:
        result = handle_hashtag(tag)
        if result is not None:
            tag_results[tag]=result
    # choose which tag we will use
    if len(tag_results) > 0:
        tag = random.choice(tag_results.keys())
        if reply:
            reply_to_user = tweet['user']['screen_name']
        else:
            reply_to_user = None
        text = compose_tweet(tag,tag_results[tag],reply_to_user)
        return {
            'text': text,
            'result': tag_results[tag],
            'in_reply_to': tweet['id']
        }
    else:
        return None

def process_tweet(tweet, reply=False):
    response = parse_tweet(tweet, reply)
    if response and response['text'] is not None:
        imgurl = FINNA_IMAGE_URL + response['result']['image']
        r = requests.get(imgurl, headers={'User-Agent': BOT_NAME})
        if len(r.content) < IMAGE_MINSIZE_BYTES:
            logging.warning("* image too small (%d bytes), aborting", len(r.content))
            return
        elif len(r.content) > IMAGE_MAXSIZE_BYTES:
            logging.info("* scaling image (size: %s bytes)", len(r.content))
            img = Image.open(StringIO.StringIO(r.content))
            img.thumbnail(IMAGE_MAXSIZE_SCALED, Image.ANTIALIAS)
            imgout = StringIO.StringIO()
            img.save(imgout, format='JPEG')
            imgdata = imgout.getvalue()
            logging.debug("* scaled image size: %s bytes", len(imgdata))
            imgout.close()
        else:
            imgdata=r.content
        
        img_id = t_upload.media.upload(media=imgdata)['media_id_string']
        if reply:
            t.statuses.update(status=response['text'], media_ids=img_id, in_reply_to_status_id=response['in_reply_to'])
        else:
            t.statuses.update(status=response['text'], media_ids=img_id)
        already_posted.add(response['result']['id'])
        logging.info("* Tweet successfully sent.")

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')

MY_TWITTER_CREDS = os.path.expanduser(CREDENTIALS_FILE)
if not os.path.exists(MY_TWITTER_CREDS):
    twitter.oauth_dance(BOT_NAME, CONSUMER_KEY, CONSUMER_SECRET,
                MY_TWITTER_CREDS)

oauth_token, oauth_secret = twitter.read_token_file(MY_TWITTER_CREDS)

t = twitter.Twitter(auth=twitter.OAuth(oauth_token, oauth_secret, CONSUMER_KEY, CONSUMER_SECRET))

t_upload = twitter.Twitter(domain='upload.twitter.com',
    auth=twitter.OAuth(oauth_token, oauth_secret, CONSUMER_KEY, CONSUMER_SECRET))

# initialize since_id by looking for our own most recent tweet
since_id = 1
for tweet in t.statuses.user_timeline(screen_name=SCREEN_NAME, count=1):
    since_id = max(since_id, int(tweet['id']))
logging.debug("* Initialized since_id to %d", since_id)

# keep track of already posted record IDs
already_posted = set()

while True:
    logging.info("* Querying for @mentions since %d", since_id)
    for tweet in t.statuses.mentions_timeline(since_id=since_id, count=STATUS_MAXCOUNT):
        since_id = max(since_id, int(tweet['id']))
        process_tweet(tweet, reply=True)

    logging.info("* Querying for status of followed users since %d", since_id)
    for tweet in t.statuses.home_timeline(since_id=since_id, count=STATUS_MAXCOUNT):
        since_id = max(since_id, int(tweet['id']))
        process_tweet(tweet)
    
    logging.info("* Sleeping...")
    time.sleep(60)
