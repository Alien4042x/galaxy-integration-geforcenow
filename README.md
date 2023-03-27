Important!!!!! <br>
I'm happy to report that the plugin is now downloading games from the Nvidia database without any issues. However, there is still a problem with loading games. Sometimes the games won't load properly and the application needs to be restarted. I'm currently working on resolving this issue, but if anyone else would like to help with the project, I would greatly appreciate it "Discord Alien4042x#2269".

# galaxy-integration-geforcenow
GoG Galaxy integration for the Geforce Now platform

**Warning: This is an early alpha level version and you shouldn't use it unless you are ok to accept any fallout.  Worst case, it could require a reinstall of GoG Galaxy.**

I'll start off with the problems:

* Uses the "Testing Platform" as there isn't an actual "Geforce Now" platform available.  I've raised a request but wouldn't hold my breath.
* GoG doesn't seem to detect all the games I add properly.  Think this is on their side as other plugin authors complain too.  But also could well be a bug with my code.
* It is Windows/Mac only and assumes that everything is where it expects (i.e. the DB)
* Some supported games may be missed due to differences in how they are named (e.g. Super Duper Edition vs Max Stuff Edition)

Now the features:

* Goes through your game library and adds a Geforce Now platform (well, "Testing Platform" for now) to any games supported in Geforce Now
* No config required, doesn't need your Geforce Now details
* Launch the game within Geforce Now directly from GoG Galaxy (even for the games misidentified)

# Installation for Windows

* Download the release
* Unzip into your plugins folder, usually `%LOCALAPPDATA%\GOG.com\Galaxy\plugins\installed`
* Restart GOG Galaxy
* Go to Setting and connect the Testing integration
* Cross fingers

# Installation for Mac OS

* Download the release
* Unzip into your plugins folder, usually `/Library/Application Support/GOG.com/Galaxy/plugins/installed`
* Restart GOG Galaxy
* Go to Setting and connect the Testing integration
* Cross fingers

# Plans

- Get GOG to add an actual platform for this
- Sort out the name detection issues
