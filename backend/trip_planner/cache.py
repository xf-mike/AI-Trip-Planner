
from typing import Dict, List, Optional, Any
from collections import OrderedDict
import threading, os, json
from concurrent.futures import ThreadPoolExecutor
from .utils import session_state_path, ensure_dir

# -------------------- LRU Cache for JSONL --------------------
class JSONLCache:
    """Thread-safe LRU cache for JSONL file reads with write-through on appends."""
    
    def __init__(self, max_size: int = 15):
        self.max_size = max_size
        self.cache: OrderedDict[str, List[Dict]] = OrderedDict()
        self.lock = threading.Lock()
    
    def get(self, path: str) -> Optional[List[Dict]]:
        """Get cached data if available, otherwise return None."""
        with self.lock:
            if path in self.cache:
                # Move to end (most recently used)
                self.cache.move_to_end(path)
                return self.cache[path].copy()  # Return copy to prevent external modifications
            return None
    
    def put(self, path: str, data: List[Dict]):
        """Cache the data, evicting LRU entry if needed."""
        with self.lock:
            if path in self.cache:
                # Update existing entry
                self.cache.move_to_end(path)
            else:
                # Add new entry, evict if needed
                if len(self.cache) >= self.max_size:
                    self.cache.popitem(last=False)  # Remove least recently used
            
            self.cache[path] = data.copy()  # Store copy to prevent external modifications
    
    def append(self, path: str, obj: Dict):
        """Append to cached data if present."""
        with self.lock:
            if path in self.cache:
                self.cache[path].append(obj)
                self.cache.move_to_end(path)  # Mark as recently used

# Global cache instance
CACHE_SIZE = int(os.environ.get("JSONL_CACHE_SIZE", "15"))
CACHED_SESSIONS = JSONLCache(max_size=CACHE_SIZE)
print(f"Chat Cache: {CACHE_SIZE} Sessions")

def _write_to_disk(path: str, obj: Any):
    """Background disk write operation."""
    try:
        with open(path, "a", encoding="utf-8") as f:
            # import time
            # time.sleep(10)  # Simulate delay for testing
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"Error writing to {path}: {e}")

_write_executor = ThreadPoolExecutor(max_workers=CACHE_SIZE, thread_name_prefix="disk-writer")

def append_session(user_id: str, session_id: str, obj: Any, async_mode: bool = True):
    """Append to JSONL file with async write."""
    path = session_state_path(user_id, session_id)
    ensure_dir(os.path.dirname(path))
    
    # Update cache immediately
    CACHED_SESSIONS.append(path, obj)
    
    # Write to disk asynchronously
    if async_mode:
        _write_executor.submit(_write_to_disk, path, obj)
    else:  # Synchronous fallback
        _write_to_disk(path, obj)

def read_session(user_id: str, session_id: str) -> List[Dict]:
    path = session_state_path(user_id, session_id)
    # check cache first
    cached = CACHED_SESSIONS.get(path)
    if cached is not None:
        return cached

    # cache miss
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except Exception:
        pass

    # store in cache
    CACHED_SESSIONS.put(path, out)
    return out