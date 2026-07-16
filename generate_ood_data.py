import json
import random

# Read existing dataset to ensure no overlaps
try:
    with open('eval/intent_dataset.json', 'r', encoding='utf-8') as f:
        existing_data = json.load(f)
    existing_prompts = {d["prompt"].lower().strip() for d in existing_data}
except FileNotFoundError:
    existing_prompts = set()

# OOD generation strategies
ood_phrases = {
    'InformationRetrievalIntent': [
        "temp right now outside",
        "fetch me data regarding the global warming phenomenon",
        "who exactly is the ceo of microsoft these days",
        "i demand to know the distance from the earth to the sun",
        "can someone tell me what the population of tokyo is",
        "need info: quantum physics",
        "search query: current president of france",
        "i was wondering if you might be able to find the definition of serendipity",
        "what's the deal with inflation",
        "give me a rundown on the history of Rome"
    ],
    'ApplicationLaunchIntent': [
        "calc",
        "exec notepad.exe",
        "it would be wonderful if you could start up discord for me",
        "i require google chrome to be running",
        "initiate the boot sequence for slack",
        "get ms word going",
        "pop open excel",
        "i wanna use paint",
        "bring up the command prompt utility",
        "fire off the calculator app"
    ],
    'WebNavigationIntent': [
        "https://www.github.com",
        "route me over to reddit",
        "i feel like browsing youtube, take me there",
        "load up the wikipedia homepage",
        "direct my browser to amazon",
        "www.netflix.com",
        "could you kindly open a tab for twitter",
        "let us proceed to the bbc news website",
        "jump into facebook",
        "surf on over to stackoverflow"
    ],
    'MediaStreamingIntent': [
        "music. now.",
        "i need some auditory stimulation, play some classical",
        "could you perhaps put on a podcast about true crime",
        "i want to vibe to some synthwave",
        "make with the tunes",
        "commence audio playback of the latest album by taylor swift",
        "i'm in the mood for a movie trailer",
        "play that one song from interstellar",
        "let the heavy metal roar",
        "start broadcasting the daily news audio"
    ],
    'FileDeletionIntent': [
        "rm -rf old_logs",
        "obliterate the temp folder",
        "i would greatly appreciate it if you purged the trash",
        "send the file named document.docx to the void",
        "this image is garbage, dump it",
        "nuke the downloads directory",
        "make the backup zip disappear",
        "destroy all unused assets",
        "clear out my junk",
        "i want this folder gone permanently"
    ],
    'GeneralizedOSIntent': [
        "screenshot",
        "copy this",
        "if it pleases you, compress these files into an archive",
        "i need to zip up this directory",
        "make a new folder here",
        "rename the image to vacation.jpg",
        "click that link",
        "scroll down please",
        "drag this over there",
        "press enter"
    ],
    'DictationIntent': [
        "start listening",
        "i'm going to speak now, write it down",
        "would you be so kind as to transcribe my voice",
        "voice dictation mode on",
        "capture my speech to text",
        "i need to dictate a letter",
        "stop typing what i say",
        "cease dictation",
        "turn off the microphone transcription",
        "record my spoken words into text"
    ],
    'AcademicResearchIntent': [
        "give me the tldr of this manuscript",
        "i beg of you to analyze this thesis",
        "extract the methodology from the attached pdf",
        "what are the main takeaways from this literature review",
        "summarize the abstract of the study",
        "i need a critique of this experimental design",
        "what dataset was utilized by the authors here",
        "fetch related works on this academic topic",
        "read this paper and explain the results",
        "cross reference these two academic articles"
    ],
    'DataModelingIntent': [
        "do stats",
        "i need you to train a deep learning classifier on this csv",
        "would you kindly perform a principal component analysis",
        "fit a support vector machine model",
        "generate a linear regression trend line",
        "i want to see a clustering of this dataframe",
        "run a time series prediction",
        "detect anomalies in this dataset",
        "clean up the missing values and plot a heatmap",
        "evaluate the random forest's performance"
    ],
    'SysUtilityIntent': [
        "vol down",
        "i'm blind, brightness down",
        "if you would be so kind, please enable the dark mode interface",
        "mute the system audio immediately",
        "turn on the airplane mode feature",
        "is the firewall active",
        "toggle my bluetooth connection",
        "i need battery saver mode on",
        "flip the switch for night light",
        "kill the wifi"
    ],
    'SchedulerIntent': [
        "calendar add: dentist 3pm",
        "remind me in 10 minutes to grab laundry",
        "i would like to schedule a meeting with the board for tuesday",
        "book a flight to london on my itinerary",
        "when is my anniversary",
        "alarm 6am",
        "set up a recurring alarm for my gym session",
        "put project deadline on the schedule",
        "i have a client call, pencil it in",
        "make sure i don't forget the grocery shopping"
    ],
    'MediaControlIntent': [
        "pause",
        "skip",
        "i would appreciate it if you could lower the volume by twenty percent",
        "fast forward this video by thirty seconds",
        "go back to the previous track",
        "stop the playback",
        "resume the movie",
        "crank the volume to the max",
        "rewind a bit",
        "shuffle the playlist"
    ],
    'WindowManagementIntent': [
        "max",
        "hide all",
        "i request that you snap this window to the right edge of the screen",
        "throw this app onto monitor number two",
        "minimize everything to the desktop",
        "close the active window",
        "tile these side by side",
        "make it fullscreen",
        "restore that minimized app",
        "switch to virtual desktop 3"
    ],
    'ConversationalIntent': [
        "yo",
        "sup",
        "good evening, artificial intelligence",
        "i find myself quite bored, do you have any jokes",
        "what is the meaning of your existence",
        "i am grateful for your assistance",
        "farewell",
        "you are quite intelligent",
        "are you listening to me",
        "let us converse about life"
    ],
    'ContinuationIntent': [
        "more",
        "go on",
        "i request that you elaborate further on that specific point",
        "please continue with your explanation",
        "keep talking",
        "what else can you tell me",
        "and then what happened",
        "dig deeper into this",
        "yes, proceed",
        "don't stop now"
    ],
    'ProcessManagementIntent': [
        "kill -9",
        "taskkill chrome",
        "i respectfully request that you terminate the background updater",
        "show me a list of all active cpu processes",
        "what is eating all my ram",
        "stop the java service",
        "close this frozen program immediately",
        "end the task for notepad",
        "which applications are running right now",
        "force quit this"
    ],
    'ProjectScaffoldIntent': [
        "init react",
        "new django project",
        "i would like to bootstrap a brand new typescript frontend",
        "scaffold an express server",
        "generate a boilerplate for a flask api",
        "create an empty git repo with a readme",
        "set up a monorepo structure using turbo",
        "start a spring boot app",
        "spin up a vue template",
        "i need a new c++ cmake skeleton"
    ],
    'DependencyInstallIntent': [
        "pip install pandas",
        "npm i lodash",
        "it is imperative that we add the tensorflow library to our environment",
        "fetch the requests module",
        "grab the latest version of react",
        "yarn add tailwindcss",
        "install the project requirements",
        "put axios in the dependencies",
        "require sqlalchemy",
        "download beautifulsoup"
    ]
}

# The expected 15 intents used in 3003 dataset are:
expected_intents = [
    'ApplicationLaunchIntent', 'WebNavigationIntent', 'InformationRetrievalIntent',
    'MediaStreamingIntent', 'FileDeletionIntent', 'ConversationalIntent',
    'ProcessManagementIntent', 'ProjectScaffoldIntent', 'DependencyInstallIntent',
    'CodeActIntent', 'AcademicResearchIntent', 'DataModelingIntent',
    'SysUtilityIntent', 'SchedulerIntent', 'WindowManagementIntent'
]

# Note: CodeActIntent wasn't in the phrase banks, but was in the dataset. Let's add it for the OOD set.
ood_phrases['CodeActIntent'] = [
    "write me a bash script",
    "i need python code to parse a csv",
    "can you draft a powershell script to monitor memory",
    "generate a regex for phone numbers",
    "code a function to reverse a linked list",
    "implement a sorting algorithm in c++",
    "build a tool that scrapes images from a webpage",
    "create a dockerfile for a node app",
    "write a macro to format this excel sheet",
    "program a bot that sends automated emails"
]

dataset = []
for intent in expected_intents:
    if intent not in ood_phrases:
        print(f"Warning: {intent} missing from ood_phrases")
        continue
    
    for phrase in ood_phrases[intent]:
        if phrase.lower().strip() in existing_prompts:
            print(f"Duplicate found: {phrase}. Appending a random token.")
            phrase = phrase + " " + str(random.randint(1000, 9999))
        
        dataset.append({
            "prompt": phrase,
            "expected_intent": intent
        })

print(f"Generated {len(dataset)} OOD items.")

with open('eval/intent_dataset_ood_test.json', 'w', encoding='utf-8') as f:
    json.dump(dataset, f, indent=4)
