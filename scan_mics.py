import sounddevice as sd
import numpy as np
import sys

print("\n=== MICROPHONE DEVICE AUDIT v2 ===")
devs = sd.query_devices()
candidates = []
for i, d in enumerate(devs):
    if d['max_input_channels'] > 0:
        name = d['name']
        print(f"  [{i}] {name} | ch={d['max_input_channels']} | sr={int(d['default_samplerate'])}")
        candidates.append(i)

print(f"\n=== LIVE RMS TEST (1s per device) ===")
CHUNK = 512
results = []

for idx in candidates:
    dev = sd.query_devices(idx)
    dev_name = dev['name']
    native_sr = int(dev['default_samplerate'])
    samples = []
    
    def cb(indata, frames, time, status):
        samples.append(indata[:, 0].copy())
    
    try:
        with sd.InputStream(samplerate=native_sr, channels=1, blocksize=CHUNK,
                            dtype='float32', device=idx, callback=cb):
            sd.sleep(1200)
            
        if samples:
            arr = np.concatenate(samples)
            rms = float(np.sqrt(np.mean((arr * 32767).astype(np.float64)**2)))
            alive = rms > 0.5
            status = "ALIVE" if alive else "DEAD-silent"
            print(f"  [{idx:2d}] {dev_name[:50]:<50} | RMS={rms:7.1f} | {status}")
            results.append((rms, idx, dev_name, native_sr))
        else:
            print(f"  [{idx:2d}] {dev_name[:50]:<50} | NO SAMPLES")
    except Exception as e:
        err = str(e).replace('\r','').replace('\n','')
        print(f"  [{idx:2d}] {dev_name[:50]:<50} | FAIL: {err}")

print("\n=== RANKED CANDIDATES ===")
results.sort(reverse=True)
for rms, idx, name, sr in results[:5]:
    print(f"  RMS={rms:.1f} -> [{idx}] {name} (sr={sr})")

if results:
    best_rms, best_idx, best_name, best_sr = results[0]
    print(f"\n>>> RECOMMENDED DEVICE: [{best_idx}] '{best_name}' | sr={best_sr} | RMS={best_rms:.1f}")
    print(f">>> USE IN stt_service.py: PREFERRED_DEVICE_INDEX = {best_idx}")
    print(f">>> USE IN stt_service.py: PREFERRED_SAMPLE_RATE = {best_sr}")
else:
    print("\n>>> NO WORKING DEVICE FOUND. Check Windows Sound Settings.")
print("\n=== AUDIT COMPLETE ===")
