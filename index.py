# -*- coding: utf-8 -*-

# http://joelgrus.com/2015/12/30/polyglot-twitter-bot-part-3-python-27-aws-lambda/
# rubberduckydev
# WhereIsItBot

from __future__ import print_function
from twython import Twython
from twython.exceptions import TwythonError
import json
import re
import urllib, urllib2
import random

with open('credentials.json') as f:
    credentials = json.loads(f.read())

client = Twython(credentials["twitter"]["consumer_key"],
                  credentials["twitter"]["consumer_secret"],
                  credentials["twitter"]["access_token_key"],
                  credentials["twitter"]["access_token_secret"])

rgx = r"where is ([a-zA-Z0-9 öäüÖÄÜß@#'\"\-]*)"
query = '"where is" -filter:retweets -filter:safe'
# https://developers.google.com/places/web-service/search
maps_search_url_format = "https://maps.googleapis.com/maps/api/place/textsearch/json?query={}&key=" + credentials["google"]["api_key"]
# https://developers.google.com/maps/documentation/static-maps/intro
maps_image_url_format = "https://maps.googleapis.com/maps/api/staticmap?center={}&zoom=5&size=400x400&format=jpg&markers=label:%7C{}&key=" + credentials["google"]["api_key"]
# "https://twitter.com/<username>/status/<tweet_id>
twitter_permalink_url_format = "https://twitter.com/{}/status/{}"

map_local_storage_location = "/tmp/map_image.jpg"

# consider removing common prefixes - my, the, etc
filtered_types = ['point_of_interest', 'establishment', 'finance', 'food', 'health', 'political', 'accounting', 'hair_care', 'laundry', 'police', 'storage', 'veterinary_care']
filtered_locations = ['it', 'everyone', 'he', 'she', 'the', 'this', 'that']
stripped_location_parts = ['[@#"]', 'https', 'http'] # order matters
vowels = ['a', 'e', 'i', 'o', 'u']

def handler(event, context):
    
    results = client.search(q=query, count=1)
    print("Found", len(results["statuses"]), "tweets matching search results")
    
    for tweet in results["statuses"]:
        
        original_tweet_text = tweet["text"]
        original_tweet_id = tweet['id_str']
        original_tweet_username = tweet['user']['screen_name']
        original_tweet_permalink = twitter_permalink_url_format.format(original_tweet_username, original_tweet_id)
        print("original tweet:", original_tweet_permalink)
        
        original_location = extract_location(original_tweet_text)
        if original_location:
            
            maps_search_response = search_places(original_location)

            maps_search_response_status = maps_search_response['status']
            if maps_search_response_status == 'OK':
                
                found_location = random.choice(maps_search_response['results'][0:3])
                name = found_location['name']
                address = found_location['formatted_address']
                chosen_type = choose_type(found_location['types'])
                
                map_image_file_path = download_map_image(address)
                
                new_tweet_text = build_tweet_text(original_tweet_username, original_location, name, chosen_type, original_tweet_permalink)
                
                publish_tweet(new_tweet_text, map_image_file_path, original_tweet_id)
                
            elif maps_search_response_status == 'ZERO_RESULTS':
                print('No Maps search results for:', original_location)
            else:
                raise LookupError("Maps search response status was not 'OK'. Was: " + maps_search_response_status)
        else:
            print("No location match found for tweet:", original_tweet_permalink, original_tweet_text)

def download_map_image(address):
    url_safe_address = urllib.quote_plus(address)
    map_image_url = maps_image_url_format.format(url_safe_address, url_safe_address)
    print("generated map url:", map_image_url)
    
    urllib.urlretrieve(map_image_url, map_local_storage_location)
    return map_local_storage_location

def build_tweet_text(username, original_location, found_place_name, found_place_type, original_tweet_permalink):
    found_place_type_text = ''
    if found_place_type:
        indicator = 'a'
        if found_place_type[0].lower() in vowels:
            indicator = 'an'
        found_place_type_text = ", " + indicator + " " + found_place_type

    # banned (for automated replies and mentions?) https://support.twitter.com/articles/76915
    # tweet_text = "@" + username + ", looking for '" + original_location + "'? I found '" + found_place_name + "'" + found_place_type_text + "!"
    tweet_text = "Looking for '" + original_location + "'? I found '" + found_place_name + "'" + found_place_type_text + "!"
    
    permalink_shortened_url = shorten_url(original_tweet_permalink)
    if len(tweet_text + permalink_shortened_url) < 140:
        # Skip the retweeting for now
        return tweet_text + " " + permalink_shortened_url
    else:
        print('Truncating original tweet permalink:', permalink_shortened_url)
        return tweet_text
    
def publish_tweet(tweet_text, img_file_path, original_tweet_id):
    image = open(img_file_path, 'rb')
    
    print("publishing:", tweet_text)
    print("tweet size:", len(tweet_text))
    
    upload_response = client.upload_media(media=image)
    print("uploaded media")
    
    # banned (for automated replies and mentions?) https://support.twitter.com/articles/76915
    # instead, we will just echo text with the map
    # client.update_status(status=tweet_text, media_ids=[upload_response['media_id']], in_reply_to_status_id=original_tweet_id)
    client.update_status(status=tweet_text, media_ids=[upload_response['media_id']])
    print("updated status")

def search_places(location):
    maps_search_url = maps_search_url_format.format(urllib.quote_plus(location))
    print("generated maps search url:", maps_search_url)
    maps_search_response_raw = urllib.urlopen(maps_search_url)
    return json.loads(maps_search_response_raw.read())

def extract_location(text):
    location = None
    
    location_match = re.search(rgx, text, re.I)
    if location_match:
        location = location_match.groups()[-1]
        location = location.strip(' \t\n\r')
        for stripped_part in stripped_location_parts:
            location = re.sub(stripped_part, '', location)
            
        # consider http://stackoverflow.com/questions/199059/im-looking-for-a-pythonic-way-to-insert-a-space-before-capital-letters for getting better results on '@MultipleWords'
        if location.lower() in filtered_locations or location.isspace():
            print("Filtering bad location: ", location)
            return None
    
    return location

def choose_type(types):
    for a_type in types:
        # https://developers.google.com/places/supported_types
        if a_type in filtered_types:
            print("Filtering type:", a_type)
            continue
        else:
            return a_type.replace("_", " ")
    print("Unable to find an interesting type")
    return None

def shorten_url(url):
    return url
    # below code is used to shorten the url to avoid retweeting
    post_url = 'https://www.googleapis.com/urlshortener/v1/url?key=' + credentials["google"]["api_key"]
    postdata = {'longUrl':url}
    headers = {'Content-Type':'application/json'}
    req = urllib2.Request(
        post_url,
        json.dumps(postdata),
        headers
    )
    ret = urllib2.urlopen(req).read()
    return json.loads(ret)['id']
