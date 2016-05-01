from .commonThread import *
from urllib.parse import quote
import urllib.request as req
from bs4 import BeautifulSoup as bs

class TwHashtagHarvester(CommonThread):
    @twitterLogger.debug()
    def execute(self):

        while not threadsExitFlag[0]:
            log("hashtags left to harvest: %s" % hashtagHarvestQueue.qsize())
            hashtag = hashtagHarvestQueue.get()
            try:
                self.harvestTweets(hashtag)
            except:
                hashtag.save()
                log("%s's tweet-harvest routine has raised an unmanaged error" % hashtag)
                raise

    @twitterLogger.debug(showArgs=True)
    def harvestTweets(self, hashtag):
        max_id = None
        if not hashtag._has_reached_begining and \
                hashtag.harvested_tweets.filter(created_at__isnull=False).count() > 0:
            max_id = hashtag.harvested_tweets.filter(created_at__isnull=False).order_by('created_at')[0]._ident - 1
        log("max_id: %s"%max_id)
        alreadyExists = 0
        while not threadsExitFlag[0]:
            twids = []
            twids = self.fetch_tweets_from_html(hashtag.term, hashtag._harvest_since,
                                                hashtag._harvest_until, max_id)
            if len(twids) == 0:
                hashtag._has_reached_begining = True
                break
            for twid in twids:
                if not max_id or twid < max_id:
                    max_id = twid - 1
                twObj, new = Tweet.objects.get_or_create(_ident=twid)
                twObj.harvested_by = hashtag
                twObj.hashtags.add(hashtag)
                twObj.save()
                if new:
                    #log("new Tweet created from %s"%hashtag)
                    alreadyExists = 0
                    tweetUpdateQueue.put(twObj)
                elif twObj.created_at != None:
                    alreadyExists += 1
                    log("alreadyExists: %s"% alreadyExists)
                    if alreadyExists >= 10: # if 10 consecutive tweets already exists, break the loop.
                        break
            #log('twids: %s' % twids)
        log("harvest finished for %s"%hashtag)
        hashtag._last_harvested = today()
        hashtag.save()

    #@twitterLogger.debug(showArgs=True)
    def fetch_tweets_from_html(self, query, since, until, max_id=None):
        params = '%s since:%s-%s-%s until:%s-%s-%s' % (query, since.year,
                                                since.month,since.day, until.year,
                                                until.month,until.day)
        if max_id: params += ' max_id:%s' % max_id
        strUrl = 'https://twitter.com/hashtag/' + quote(params)
        #log('strUrl: %s'%strUrl)
        url = req.Request(strUrl, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:45.0) Gecko/20100101 Firefox/45.0'})
        try:
            data = req.urlopen(url, timeout=5)
        except:
            log("urlopen failed, retrying in 1 sec")
            time.sleep(1)
            return self.fetch_tweets_from_html(query,since,until,max_id)
        page = bs(data, "html.parser")
        tweets = page.find_all('li', {"data-item-type": "tweet"})
        tweet_list = [int(tweet['data-item-id']) for tweet in tweets if tweet.has_attr('data-item-id')]
        return tweet_list