# FinnaBot

This is a Twitter bot that publishes pictures from the Finna portal

# Installing

You need Python 2.x with the following libraries:

* twitter
* requests
* PIL

You can install the dependencies using `pip install` or your distribution's package manager.

# Operation

When started up, this bot will perform searches for tweets by followers as
well as @mentions by other Twitter users using the Twitter API. From each
tweet, it will extract hashtags and search for Finna images via the Finna
API using the hashtag as keyword. If it finds any images for any hashtags,
it will compose a tweet using that image. @mentions will be responded to as
replies to the original tweet.

# Licence

CC0
