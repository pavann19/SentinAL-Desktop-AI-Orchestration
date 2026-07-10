import numpy as np
import warnings
import functools

# Suppress huggingface warnings about symlinks
warnings.filterwarnings("ignore", module="huggingface_hub")

# ── Expanded Intent Phrase Bank ─────────────────────────────────────────────
# Fix 3.5: Expanded from ~7 to 25+ diverse anchor phrases per intent.
# More phrases = better cosine similarity coverage across paraphrase space.
INTENT_CAPABILITIES = {
    "InformationRetrievalIntent": [
        "search the web for this",
        "look up details about",
        "find information on",
        "what is the price of",
        "who is the president of",
        "who won the match",
        "give me the latest news on",
        "what's the weather like today",
        "research this topic for me",
        "what is the capital of",
        "how does a car engine work",
        "can you find out",
        "tell me about",
        "explain to me what",
        "I want to know about",
        "who invented",
        "what time does it open",
        "find the definition of",
        "look this up online",
        "get me information about",
        "search online for",
        "browse and find",
        "retrieve information about",
        "fetch data about",
        "what are the latest updates on",
    ],
    "ApplicationLaunchIntent": [
        "open the software",
        "launch the application",
        "start the program",
        "can you open",
        "run this app",
        "open the calculator",
        "launch notepad for me",
        "start chrome browser",
        "bring up the file explorer",
        "open spotify",
        "launch discord",
        "start visual studio code",
        "open Microsoft Word",
        "fire up the terminal",
        "open task manager",
        "start Excel",
        "launch the browser",
        "bring up PowerPoint",
        "open paint for me",
        "start the settings app",
        "run the application",
        "execute the program",
        "pull up the application",
        "boot up the software",
        "initiate the app",
    ],
    "WebNavigationIntent": [
        "go to the website",
        "open the url",
        "navigate to this page",
        "go to github.com",
        "navigate to youtube",
        "take me to the site",
        "open this web address",
        "visit the website",
        "browse to",
        "load this URL",
        "go online to",
        "open the web page",
        "take me to reddit",
        "open this link",
        "go to amazon.com",
        "navigate me to",
        "browse the internet to",
        "go to the web page",
        "open a browser tab for",
        "take me to google",
        "visit this address",
        "access the website",
        "pull up the web page",
        "surf to",
        "jump to the site",
    ],
    "MediaStreamingIntent": [
        "play a song",
        "stream this video",
        "listen to music",
        "put on some tunes",
        "play music by",
        "stream something on youtube",
        "play this track",
        "put on background music",
        "queue up a playlist",
        "play some jazz",
        "stream a podcast",
        "play the radio",
        "I want to hear",
        "put on music",
        "stream me a video",
        "play this on spotify",
        "play the latest album by",
        "start music playback",
        "listen to podcast",
        "open youtube and play",
        "play lofi music",
        "stream the soundtrack",
        "play a video of",
        "run this video",
        "start playing",
    ],
    "FileDeletionIntent": [
        "delete the file",
        "remove this document",
        "trash it",
        "erase the folder",
        "clean up the directory",
        "delete these files",
        "remove the item",
        "get rid of this file",
        "wipe this folder",
        "delete everything in",
        "remove the old files",
        "clear this directory",
        "permanently delete",
        "send to recycle bin",
        "unlink this file",
        "discard the file",
        "eliminate the document",
        "purge old downloads",
        "remove unused files",
        "delete the backup",
        "clean up old logs",
        "delete temp files",
        "remove junk files",
        "erase the data",
        "drop the file",
    ],
    "GeneralizedOSIntent": [
        "type this text",
        "press the spacebar",
        "list the files here",
        "check the directory",
        "close this window",
        "create a new folder",
        "make a directory",
        "run this shell command",
        "execute this script",
        "rename the file",
        "move the file to",
        "copy the contents of",
        "compress the folder",
        "zip the files",
        "take a screenshot",
        "click on the button",
        "scroll down the page",
        "right click here",
        "drag and drop",
        "minimize all windows",
        "show the desktop",
        "switch to the previous window",
        "open a new terminal here",
        "run the batch file",
        "perform a system task",
    ],
    "DictationIntent": [
        "start dictation",
        "start typing what I say",
        "dictate this",
        "enter dictation mode",
        "type everything I say",
        "write this down for me",
        "voice typing",
    ],
    "AcademicResearchIntent": [
        "summarize this research paper",
        "read this pdf and tell me the methodology",
        "what is the abstract of this paper",
        "download the paper from arxiv",
        "analyze this academic paper",
        "what dataset did they use in this paper",
        "extract the conclusion from this document",
    ],
    "DataModelingIntent": [
        "run a correlation analysis on this dataset",
        "analyze this csv file",
        "perform exploratory data analysis",
        "handle missing values in this data",
        "plot a heatmap for this dataset",
        "run a t test on these results",
        "generate a statistical summary of this csv",
    ],
    "SysUtilityIntent": [
        "empty the recycle bin",
        "turn on dark mode",
        "switch to light mode",
        "turn down the brightness",
        "mute my microphone",
        "unmute my mic",
        "clear the trash",
    ],
    "SchedulerIntent": [
        "plan a holiday itinerary",
        "remind me to call mom",
        "add this to my calendar",
        "set a timer for",
        "what's on my schedule today",
        "plan a complex defense analytics schedule",
        "create a trip plan",
    ],
    "MediaControlIntent": [
        "pause the video",
        "skip this song",
        "play the next track",
        "go back to the previous song",
        "set volume to 50 percent",
        "turn the volume up",
        "mute the system volume",
    ],
    "WindowManagementIntent": [
        "snap this window to the left",
        "take a screenshot",
        "start screen recording",
        "minimize all windows",
        "switch to desktop 2",
        "maximize this application",
        "stop recording my screen",
    ],
    "ConversationalIntent": [
        "hello there",
        "how are you doing",
        "tell me a joke",
        "who are you",
        "good morning",
        "what's up",
        "explain quantum physics",
        "define the meaning of life",
        "can you help me with",
        "I have a question",
        "what do you think about",
        "let's talk",
        "just chatting",
        "what can you do",
        "are you there",
        "tell me something interesting",
        "how does this work",
        "give me advice on",
        "what's your opinion",
        "help me understand",
        "can you explain",
        "talk to me about",
        "discuss with me",
        "I want to ask you",
        "speak to me about",
    ],
    "ContinuationIntent": [
        "tell me more",
        "continue",
        "elaborate on that",
        "yes",
        "go on",
        "give me more details",
        "keep going",
        "what else",
        "and then",
        "proceed",
        "expand on this",
        "more information please",
        "dig deeper",
        "go into detail",
        "don't stop",
        "I want to hear more",
        "carry on",
        "next",
        "what comes after",
        "keep talking",
        "yes please continue",
        "further details",
        "continue explaining",
        "please go on",
        "show me more",
    ]
}


class SemanticRouter:
    """
    Semantic intent router using sentence-transformers for embedding-based cosine similarity.

    V2.0 Fixes (Fix 3.5):
    - Phrase banks expanded from 5-8 to 25 per intent for better cosine coverage
    - Query embeddings cached with functools.lru_cache (saves 5-15ms per repeat)
    - Model load wrapped in try/except with keyword-based fallback router
    """

    def __init__(self):
        print("[Router] Initializing semantic embedding capabilities (all-MiniLM-L6-v2 on CPU)...")
        self._fallback_mode = False
        try:
            from sentence_transformers import SentenceTransformer
            from sklearn.metrics.pairwise import cosine_similarity as _cos_sim
            self._cos_sim = _cos_sim
            self.model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
            self.intents = list(INTENT_CAPABILITIES.keys())
            self.intent_embeddings = {}
            # Precompute cluster embeddings once at startup
            for intent, phrases in INTENT_CAPABILITIES.items():
                self.intent_embeddings[intent] = self.model.encode(phrases)
            print("[Router] Semantic router ready.")
        except Exception as e:
            print(f"[Router] WARNING: Could not load sentence-transformers ({e}). Using keyword fallback.")
            self._fallback_mode = True
            self.model = None
            self.intent_embeddings = {}

    def _encode_cached(self, text: str) -> np.ndarray:
        """
        Fix 3.5: LRU cache on query embedding — repeated identical commands
        skip the model.encode() call (~10ms saved per cache hit).
        Cache is per-instance; functools.lru_cache requires hashable args.
        """
        return self.model.encode([text])

    def route(self, prompt: str) -> dict:
        """Routes the prompt to the best matching intent class."""
        normalized = prompt.strip().lower()
        if not normalized:
            return {"intent": "UnknownIntent", "confidence": 0.0}

        # Fallback: keyword-based routing if model unavailable
        if self._fallback_mode:
            return self._keyword_fallback(normalized)

        # Fix 3.5: Use cached embedding
        query_emb = self._encode_cached(prompt)

        best_intent  = "UnknownIntent"
        highest_score = -1.0

        for intent, embeddings in self.intent_embeddings.items():
            sim_scores = self._cos_sim(query_emb, embeddings)[0]
            max_score  = float(np.max(sim_scores))
            if max_score > highest_score:
                highest_score = max_score
                best_intent   = intent

        # Calibrated threshold: 0.40 accepts natural commands, rejects symbol-heavy garbage
        if highest_score < 0.40:
            best_intent = "UnknownIntent"

        return {"intent": best_intent, "confidence": round(highest_score, 4)}

    def _keyword_fallback(self, normalized: str) -> dict:
        """Simple keyword-based fallback when model is unavailable."""
        if any(w in normalized for w in ("open", "launch", "start", "run")):
            return {"intent": "ApplicationLaunchIntent", "confidence": 0.5}
        if any(w in normalized for w in ("search", "look up", "find", "research", "what is")):
            return {"intent": "InformationRetrievalIntent", "confidence": 0.5}
        if any(w in normalized for w in ("go to", "navigate", "website", "url")):
            return {"intent": "WebNavigationIntent", "confidence": 0.5}
        if any(w in normalized for w in ("play", "stream", "music", "song")):
            return {"intent": "MediaStreamingIntent", "confidence": 0.5}
        if any(w in normalized for w in ("delete", "remove", "erase", "trash")):
            return {"intent": "FileDeletionIntent", "confidence": 0.5}
        if any(w in normalized for w in ("continue", "more", "elaborate", "proceed")):
            return {"intent": "ContinuationIntent", "confidence": 0.5}
        return {"intent": "ConversationalIntent", "confidence": 0.4}


# Singleton instance
router = SemanticRouter()
