
from AspiraUser.models import UserProfile
from django.template.loader import render_to_string
from django.core.mail import send_mail, mail_admins, EmailMessage
from django.contrib.auth.models import User
from .twUserUpdater import *
from .twFriendshipUpdater import *
from .twFollowersUpdater import *
from .twFavTweetUpdater import *
from .twUserHarvester import *
from .twRetweeterHarvester import *
from .tweetUpdater import *
from .twHashtagHarvester import *
from django.core.paginator import Paginator

myEmailMessage = ["Twitter harvest routine has completed successfully"]
myEmailTitle = ["Twitter harvest completed"]
threadList = [[]]

RAMUSAGELIMIT = 600000000 # in bytes
GRAPHRAMUSAGE = False

@twitterLogger.debug()
def harvestTwitter():
    #resetErrorsTwUser("_error_on_network_harvest")
    #resetErrorsTwUser("_error_on_update")
    #clearNetworkHarvestTime()
    all_profiles = UserProfile.objects.filter(twitterApp_parameters_error=False)
    clientList = getClientList(all_profiles)
    all_profiles = all_profiles.filter(twitterApp_parameters_error=False) # insures that his/her twitter app is valid
    if len(all_profiles) == 0:
        log('No valid Twitter client exists!')
        myEmailTitle[0] = 'Twitter harvest has not launched'
        myEmailMessage[0] = 'No valid Twitter client exists! (reseting them all)'
        for profile in UserProfile.objects.all():
            profile.twitterApp_parameters_error = False
            profile.save()
        return
    clientQueue.maxsize = len(clientList)
    log('Valid Twitter clients: %s' % [str(client) for client in clientList])
    for client in clientList:
        clientQueue.put(client)

    if TWUser.objects.filter(_ident__isnull=True, _error_on_update=False).exists():
        updateNewUsers()

    for thread in [
        (launchNetworkHarvestThreads, 'launchNetworkHarvest', {'profiles': all_profiles}),
        (launchTweetHarvestThreads, 'launchTweetHarvest', {'profiles': all_profiles}),
        (launchRetweeterHarvestThreads, 'launchRetweeterHarvest', {'profiles': all_profiles}),
        (launchTweetUpdateThread, 'launchTweetUpdateHarvest', {'profiles': all_profiles}),
        (launchHashagHarvestThreads, 'launchHashagHarvest', {'profiles': all_profiles}),
        (launchUpdaterTread, 'launchUpdater', {'profiles': all_profiles}),
        (plotRamUsage, 'ramUsage', None),
    ]:
        t = threading.Thread(target=thread[0],name=thread[1],kwargs=thread[2])
        threadList[0].append(t)
        t.start()

    time.sleep(10)
    waitForThreadsToEnd()


def plotRamUsage():
    if GRAPHRAMUSAGE:
        csvfile = open(os.path.join(LOG_DIRECTORY, 'twitterMemLog.csv'), 'w')
        header = 'time,memory usage,updateQueue,friendsUpdateQueue,followersUpdateQueue,favoriteTweetUpdateQueue,userHarvestQueue,hashtagHarvestQueue,tweetUpdateQueue,twRetweetUpdateQueue\n'
        csvfile.write(header)
        csvfile.close()
        #log(header)
        while not threadsExitFlag[0]:
            time.sleep(5)
            csvfile = open(os.path.join(LOG_DIRECTORY, 'twitterMemLog.csv'), 'a')
            s = '%s,%s' % (elapsedSeconds(), process.memory_info()[0])
            for queue in allQueues:
                s +=',%s'%queue.qsize()
            #log(s)
            s+= '\n'
            csvfile.write(s)
            csvfile.close()


def send_routine_email(title,message):
    logfilepath = os.path.join(LOG_DIRECTORY, 'twitter.log')
    logfile = open(logfilepath, 'r')
    adresses = [user.email for user in User.objects.filter(is_superuser=True)]
    try:
        email = EmailMessage(title, message)
        email.attachments = [('twitterlogger.log', logfile.read(), 'text/plain')]
        email.to = adresses
        email.from_email = 'Aspira'
        email.send()
        print('%s - Routine email sent to %s'%(datetime.now().strftime('%y-%m-%d_%H:%M'),adresses))
    except Exception as e:
        print('Routine email failed to send')
        print(e)
        twitterLogger.exception('An error occured while sending an email to admin')

#@profile
#@twitterLogger.debug(showArgs=True)
def updateNewUsers():
    allNewUsers = list(TWUser.objects.filter(_ident__isnull=True, _error_on_update=False))
    userlists = [allNewUsers[i:i+100] for i in range(0,len(allNewUsers), 100)]
    #log("userlists: %s"% userlists)
    for userList in userlists:
        client = getClient('lookup_users')
        try:
            responses = client.call('lookup_users', screen_names=[user.screen_name for user in userList])
        except tweepy.error.TweepError as e: #None of the usernames exists
            for falseUser in userList:
                log('%s has returned no result' % falseUser)
                falseUser._error_on_update = True
                falseUser.save()
        returnClient(client)
    for response in responses:
        user = next((user for user in allNewUsers if user.screen_name == response._json['screen_name']), None)
        #log('user: %s'%user)
        if user:
            user.UpdateFromResponse(response._json)
            allNewUsers.remove(user)
    for user in allNewUsers:
        #log('%s has returned no result' % user)
        user._error_on_update = True
        user.save()


#@profile
#@twitterLogger.debug()
def launchHashagHarvestThreads(*args, **kwargs):
    profiles = kwargs['profiles']
    hashtags = profiles[0].twitterHashtagsToHarvest.all()
    #log("profiles: %s"% profiles)
    for profile in profiles:
        #log(profile)
        hashtags = hashtags | profile.twitterHashtagsToHarvest.all()

    harvestThread = []
    threadNames = ['hashtager1']
    for threadName in threadNames:
        thread = TwHashtagHarvester(threadName)
        thread.start()
        harvestThread.append(thread)

    put_batch_in_queue(hashtagHarvestQueue, orderQueryset(hashtags, '_last_harvested'))


#@profile
#@twitterLogger.debug()
def launchUpdaterTread(*args, **kwargs):
    priority_updates = orderQueryset(TWUser.objects.filter(harvested_by__isnull=False, _error_on_update=False),
                                       '_last_updated', delay=0.5)
    allUserstoUpdate = orderQueryset(TWUser.objects.filter(_error_on_update=False)
                                     .exclude(pk__in=priority_updates), '_last_updated', delay=5)
    updateThreads = []

    threadNames = ['userUpdater1','userUpdater2','userUpdater3']
    for threadName in threadNames:
        thread = TwUserUpdater(threadName)
        thread.start()
        updateThreads.append(thread)

    put_batch_in_queue(updateQueue, priority_updates)

    #put_batch_in_queue(updateQueue, allUserstoUpdate)

    '''
    chunksize = 1000
    i = 0
    while True:
        users = allUserstoUpdate.filter(pk__gt=i, pk__lt=i + chunksize)
        log('users.count(): %s'% users.count())
        if users.count() == 0: return
        for user in users.iterator():
            if threadsExitFlag[0]: return
            if QUEUEMAXSIZE == 0 or updateQueue.qsize() < QUEUEMAXSIZE:
                updateQueue.put(user)
            else:
                time.sleep(1)
        i += chunksize
    log('launchUpdaterTread HAS FINISHED')
    '''

    paginator = Paginator(allUserstoUpdate, 1000)
    for page in range(1, paginator.num_pages + 1):
        for user in paginator.page(page).object_list:
            if threadsExitFlag[0]: return
            if QUEUEMAXSIZE == 0 or updateQueue.qsize() < QUEUEMAXSIZE:
                updateQueue.put(user)
            else:
                time.sleep(1)


#@profile
#@twitterLogger.debug()
def launchTweetHarvestThreads(*args, **kwargs):
    profiles = kwargs['profiles']
    twUsers = profiles[0].twitterUsersToHarvest.filter(_error_on_harvest=False,protected=False)
    for profile in profiles[1:]:
        twUsers = twUsers | profile.twitterUsersToHarvest.filter(_error_on_harvest=False,protected=False)

    #twUsers = orderQueryset(twUsers, '_last_tweet_harvested', delay=1)
    priorities = [(twUser, twUser.statuses_count - twUser.tweets.count()) for twUser in twUsers]
    priorities.sort(key=lambda x: x[1], reverse=True)
    twUsers = [prioritie[0] for prioritie in priorities]

    threadNames = ['harvester1', "harvester2"]
    for threadName in threadNames:
        thread = TwUserHarvester(threadName)
        thread.start()
        threadList[0].append(thread)

    log('preparing to queue %s items in %s' % (len(twUsers), userHarvestQueue._name))
    for item in twUsers:
        if threadsExitFlag[0]: break
        if QUEUEMAXSIZE == 0 or userHarvestQueue.qsize() < QUEUEMAXSIZE:
            userHarvestQueue.put(item)
        else:
            time.sleep(1)
    log('Finished adding %s items in %s'%(len(twUsers), userHarvestQueue._name), showTime=True)
    #put_batch_in_queue(userHarvestQueue, twUsers)



#@profile
#@twitterLogger.debug()
def launchNetworkHarvestThreads(*args, **kwargs):
    profiles = kwargs['profiles']
    twUsers = profiles[0].twitterUsersToHarvest.filter(_error_on_network_harvest=False,protected=False)
    for profile in profiles[1:]:
        twUsers = twUsers | profile.twitterUsersToHarvest.filter(_error_on_network_harvest=False,protected=False)

    thread1 = TwFriendshipUpdater('friender1')
    threadList[0].append(thread1)
    thread1.start()
    thread2 = TwFollowersUpdater('follower1')
    threadList[0].append(thread2)
    thread2.start()
    thread3 = TwFavTweetUpdater('favtweeter1')
    threadList[0].append(thread3)
    thread3.start()

    put_batch_in_queue(friendsUpdateQueue, orderQueryset(twUsers, '_last_friends_harvested'))
    put_batch_in_queue(followersUpdateQueue, orderQueryset(twUsers, '_last_followers_harvested'))
    put_batch_in_queue(favoriteTweetUpdateQueue, orderQueryset(twUsers, '_last_fav_tweet_harvested'))


#@profile
#@twitterLogger.debug()
def launchRetweeterHarvestThreads(*args, **kwargs):
    profiles = kwargs['profiles']
    twUsers = TWUser.objects.none()
    for profile in profiles:
        twUsers = twUsers | profile.twitterUsersToHarvest.filter(_error_on_network_harvest=False,protected=False)

    tweets = Tweet.objects.none()
    for twUser in twUsers:
        tweets = tweets | twUser.tweets.filter(_error_on_retweet_harvest=False,
                                               deleted_at__isnull=True,
                                               retweet_of__isnull=True)

    tweets = orderQueryset(tweets, '_last_retweeter_harvested', delay=2)

    threadNames = ['retweeter1','retweeter2']
    for threadName in threadNames:
        thread = TwRetweeterHarvester(threadName)
        threadList[0].append(thread)
        thread.start()

    put_batch_in_queue(twRetweetUpdateQueue, tweets)


#@profile
#@twitterLogger.debug()
def launchTweetUpdateThread(*args, **kwargs):
    profiles = kwargs['profiles']
    twUsers = TWUser.objects.none()
    for profile in profiles:
        twUsers = twUsers | profile.twitterUsersToHarvest.filter(_error_on_harvest=False,protected=False)

    tweets = Tweet.objects.none()
    for twUser in twUsers:
        tweets = tweets | twUser.tweets.filter(_error_on_update=False,
                                               deleted_at__isnull=True,
                                               retweet_of__isnull=True)

    tweets = orderQueryset(tweets, '_last_updated',delay=2)

    threadNames = ['tweetUpdater1', 'tweetUpdater2']
    for name in threadNames:
        thread = TweetUpdater(name)
        threadList[0].append(thread)
        thread.start()

    put_batch_in_queue(tweetUpdateQueue, tweets)

#@twitterLogger.debug()
def getClientList(profiles):
    clientList = []
    for profile in profiles:
        client = createTwClient(profile)
        if client:
            clientList.append(client)
    return clientList

#@twitterLogger.debug()
#@profile()
def orderQueryset(queryset, dateTimeFieldName,delay=1):
    isNull = dateTimeFieldName+"__isnull"
    lt = dateTimeFieldName+"__lt"
    ordered_elements = queryset.filter(**{isNull:True}) | \
                       queryset.filter(**{lt: xDaysAgo(delay)}).order_by(dateTimeFieldName)
    return ordered_elements

#@twitterLogger.debug()
def createTwClient(profile):
    try:
        client = Client(
            name = "%s's Twitter app"%profile.user,
            ck = profile.twitterApp_consumerKey,
            cs = profile.twitterApp_consumer_secret,
            atk = profile.twitterApp_access_token_key,
            ats = profile.twitterApp_access_token_secret,
        )
        return client
    except tweepy.error.TweepError:
        profile.twitterApp_parameters_error = True
        profile.save()
        twitterLogger.exception('%s has got an invalid Twitter app'%profile.user)
        return None


def put_batch_in_queue(queue, queryset):
    log('preparing to queue %s items in %s'%(queryset.count(), queue._name))
    for item in queryset.iterator():
        if threadsExitFlag[0]: break
        if QUEUEMAXSIZE == 0 or queue.qsize() < QUEUEMAXSIZE:
            queue.put(item)
        else:
            time.sleep(1)
    log('Finished adding %s items in %s'% (queryset.count(),queue._name), showTime=True)

#@twitterLogger.debug()
def clearUpdatedTime():
    for twUser in TWUser.objects.filter(_last_updated__isnull=False):
        twUser._last_updated = None
        twUser.save()

#@twitterLogger.debug()
def clearNetworkHarvestTime():
    for twUser in TWUser.objects.filter(_last_friends_harvested__isnull=False):
        twUser._last_friends_harvested = None
        twUser.save()
    for twUser in TWUser.objects.filter(_last_followers_harvested__isnull=False):
        twUser._last_followers_harvested = None
        twUser.save()
    for twUser in TWUser.objects.filter(_last_fav_tweet_harvested__isnull=False):
        twUser._last_fav_tweet_harvested = None
        twUser.save()

@twitterLogger.debug(showArgs=True)
def resetErrorsTwUser(errorMarker):
    for twuser in TWUser.objects.filter(**{errorMarker:True}):
        setattr(twuser, errorMarker, False)
        twuser.save()


import io, csv, types
@twitterLogger.debug()
def waitForThreadsToEnd():
    notEmptyQueuesNum = -1
    while notEmptyQueuesNum != 0 and exceptionQueue.empty():
        time.sleep(3)
        if process.memory_info()[0] >= RAMUSAGELIMIT:
            log('MEMORY USAGE LIMIT EXCEDED!')
            myEmailTitle[0] = 'MEMORY USAGE LIMIT EXCEDED!'
            myEmailMessage[0] = 'Python script memory usage has exceded the set limit (%s Mb)'% \
                                (RAMUSAGELIMIT/1000000)
            queues = allQueues
            return stopAllThreads()
        notEmptyQueues = [(queue._name, queue.qsize()) for queue in allQueues if not queue.empty()]
        if len(notEmptyQueues) != notEmptyQueuesNum and len(notEmptyQueues) <= 20:
            log('Working Queues: %s' % notEmptyQueues)
            notEmptyQueuesNum = len(notEmptyQueues)
    return stopAllThreads()


@twitterLogger.debug()
def stopAllThreads():
    time.sleep(3)
    threadsExitFlag[0] = True
    t = time.time()
    aliveThreads = [thread.name for thread in threadList[0] if thread.isAlive()]
    while len(aliveThreads) > 0 or not exceptionQueue.empty():
        if t + 10 < time.time():
            t = time.time()
            lastAliveThreads = aliveThreads
            aliveThreads = [thread.name for thread in threadList[0] if thread.isAlive()]
            if aliveThreads != lastAliveThreads:
                log('Alive Threads: %s' % aliveThreads)
        if not exceptionQueue.empty():
            (e, threadName) = exceptionQueue.get()
            try:
                raise e
            except:
                myEmailMessage[0] = 'An exception has been retrieved from a Thread. (%s)' % threadName
                myEmailTitle[0] = 'SNH - Twitter harvest routine error'
                logerror(myEmailMessage[0])


def cleanDuplicates():
    duplicates = TWUser.objects.filter(_has_duplicate=True)
    if duplicates:
        log("SOME TWUSERS HAVE DUPLICATES!")
        for duplicate in duplicates:
            log("%s has at least a duplicate"%duplicate)
            duplicate._error_on_update = True
            duplicate.save()
    else:
        log('NO DUPLICATE TWUSER FOUND')