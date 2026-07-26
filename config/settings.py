# brain_config.py
# Unified LLM Configuration & Failover Management for SentinAL.

import os

from dotenv import load_dotenv

# Load environment variables at module level
load_dotenv()

class BrainConfig:
    """
    Centralized factory for LLM instances. 
    Implements failover chains and standardizes model parameters.
    """
    
    @staticmethod
    def get_local_llm(num_predict: int = 1024):
        """Returns a ChatOllama instance (local-first priority)."""
        from langchain_ollama import ChatOllama
        model_name = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
        return ChatOllama(model=model_name, temperature=0, num_predict=num_predict)

    @staticmethod
    def get_cloud_llm(max_tokens: int = 1024):
        """Returns a ChatGroq instance (cloud-first priority)."""
        api_key = os.getenv("GROQ_API_KEY", "").strip(' \'"')
        if not api_key:
            return None
            
        from langchain_groq import ChatGroq
        model_name = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        return ChatGroq(model_name=model_name, groq_api_key=api_key, temperature=0, max_tokens=max_tokens)

    @staticmethod
    def get_routed_llm(prompt: str, purpose: str = "Execution"):
        """
        Privacy-aware routing with an automatic failover chain:
        1. Analyzes prompt for PII/Sensitive data via privacy_guard.
        2. If 'local' route: returns Ollama.
        3. If 'cloud' route: tries Groq, fails over to Ollama if API/Network fails.
        """
        from system_services.privacy_router import privacy_guard
        decision = privacy_guard.analyze(prompt)
        route = decision["route"]
        reason = decision["reason"]

        if route == "local":
            print(f"[AUDIT] Privacy Router [{purpose}]: LOCAL-ONLY - {reason}")
            return BrainConfig.get_local_llm()

        print(f"[AUDIT] Privacy Router [{purpose}]: CLOUD-SAFE - {reason}")
        
        # Cloud Failover Chain: Groq -> Ollama
        # V2.7 FIX: Actually invoke a ping to verify connectivity (was a no-op before)
        cloud_llm = BrainConfig.get_cloud_llm()
        if cloud_llm:
            try:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(cloud_llm.invoke, [("system", "ping")])
                    future.result(timeout=2.0)  # 2 second connectivity test
                return cloud_llm
            except concurrent.futures.TimeoutError:
                print("[RELIABILITY] Cloud LLM ping timed out. Falling back to local.")
            except Exception as e:
                print(f"[RELIABILITY] Cloud LLM ping failed ({e}). Falling back to local.")

        return BrainConfig.get_local_llm()

    @staticmethod
    def get_correction_llm():
        """Specialized lightweight instance for STT polishing."""
        return BrainConfig.get_local_llm(num_predict=100)
