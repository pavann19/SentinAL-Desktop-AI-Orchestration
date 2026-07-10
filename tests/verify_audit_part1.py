import asyncio
import json
import websockets

async def test_neural_link_refactor():
    uri = "ws://localhost:8000/ws/agent"
    try:
        async with websockets.connect(uri) as websocket:
            print("[Test] Connected to SentinAL WebSocket.")
            
            # Test Case 1: Neural Research
            prompt = "What is the current price of Bitcoin?"
            print(f"[Test] Sending prompt: '{prompt}'")
            await websocket.send(json.dumps({"text": prompt}))
            
            stages_seen = []
            while True:
                response = await websocket.recv()
                msg = json.loads(response)
                print(f"[Received] {msg}")
                
                if msg["type"] == "execution_step":
                    stage = msg.get("stage")
                    if stage:
                        stages_seen.append(stage)
                
                if msg["type"] == "final_response":
                    print(f"[Final Result] {msg['message']}")
                    break
                
                if msg["type"] == "error":
                    print(f"[Error] {msg['message']}")
                    break
            
            print(f"[Audit Summary] Stages seen in order: {stages_seen}")
            
            # Verification: Sequence Check
            expected_start = ["perception", "governance", "researching"]
            if stages_seen[:3] == expected_start:
                print("✅ [SUCCESS] Correct sequence: Perception -> Governance -> Researching.")
            else:
                print(f"❌ [FAILURE] Incorrect sequence. Got: {stages_seen}")

    except Exception as e:
        print(f"❌ [Test Error] Could not connect: {e}")

if __name__ == "__main__":
    asyncio.run(test_neural_link_refactor())
