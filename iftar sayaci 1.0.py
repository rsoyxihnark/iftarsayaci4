#!/usr/bin/env python3
# ---------------------------------------------------------------------
# Minimal Temel İthalatlar (modüle manager için)
# ---------------------------------------------------------------------
import os
import sys
import threading
import subprocess
import time
import io
import configparser
import functools
import importlib
import json
import logging
import re
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, TypeVar, Union
import concurrent.futures

APP_VERSION = "1.0.1"

class StreamToLogger(io.TextIOBase):
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.level, line.rstrip())
        return len(buf)

    def flush(self):
        pass

    def isatty(self):
        return False

T = TypeVar("T")

def get_check_module_updates_from_settings() -> bool:
    settings_path = os.path.join(os.getcwd(), "settings.ini")
    config = configparser.ConfigParser()
    if os.path.exists(settings_path):
        config.read(settings_path, encoding="utf-8")
        return config.get("AYARLAR", "check_module_updates", fallback="False").lower() == "true"
    return False

CHECK_MODULE_UPDATES = get_check_module_updates_from_settings()

# ---------------------------------------------------------------------
# ModuleManager: Tüm üçüncü taraf kütüphane import ve kurulumu bu sınıf tarafından yönetilir.
# ---------------------------------------------------------------------
class ModuleManager:
    VALID_PACKAGE_REGEX = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(?:[.-][a-zA-Z0-9_]+)*$")

    @staticmethod
    def dynamic_import(module_name: str) -> Any:
        if not ModuleManager.VALID_PACKAGE_REGEX.match(module_name):
            logging.error("Geçersiz modül adı: %s", module_name)
            raise ImportError(f"Geçersiz modül adı: {module_name}")
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError:
            logging.info("Modül '%s' bulunamadı, kurulumu deneniyor...", module_name)
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        subprocess.run,
                        [sys.executable, "-m", "pip", "install", module_name, "--user"],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    logging.info("%s kuruluyor... lütfen bekleyin.", module_name)
                    future.result(timeout=30)
            except subprocess.CalledProcessError as e:
                stderr_output = e.stderr or ""
                if "Could not fetch URL" in stderr_output or "Failed to establish a new connection" in stderr_output:
                    error_msg = f"Network error: {module_name} kurulumu başarısız oldu. Lütfen internet bağlantınızı kontrol edin."
                elif "No matching distribution found" in stderr_output:
                    error_msg = f"Package not found: {module_name} kurulumu başarısız oldu. Lütfen modül adını kontrol edin."
                elif "Permission denied" in stderr_output:
                    error_msg = f"Permission error: {module_name} kurulumu başarısız oldu. Lütfen sistem izinlerini kontrol edin."
                else:
                    error_msg = (
                        f"Dinamik modül kurulumu başarısız oldu: {module_name}. "
                        "Lütfen ağ bağlantınızı ve pip yapılandırmanızı kontrol edin."
                    )
                logging.error(error_msg)
                raise ImportError(error_msg) from e
            return importlib.import_module(module_name)

    @dataclass
    class ModuleInfo:
        mod_name: str
        pkg: Optional[str]
        ver: Optional[str] = None

    ALLOWED_MODULES = {
        "ast", "asyncio", "babel", "babel.dates", "certifi", "collections",
        "concurrent.futures", "configparser", "datetime", "difflib", "dotenv",
        "geopy", "hashlib", "hijridate", "logging.handlers",
        "ntplib", "pycountry", "queue", "random", "requests", "rich", "signal",
        "tkinter", "types", "tzdata", "unicodedata", "urllib.parse", "zoneinfo"
    }

    @classmethod
    def install_module(cls, module_info: "ModuleManager.ModuleInfo") -> None:
        pkg = module_info.pkg if module_info.pkg else module_info.mod_name
        if not cls.VALID_PACKAGE_REGEX.match(pkg) or any(c in pkg for c in ";|&"):
            raise ValueError(f"Geçersiz veya tehlikeli paket adı: {pkg}")
        version_spec = f"=={module_info.ver}" if module_info.ver else ""
        command = [sys.executable, "-m", "pip", "install", f"{pkg}{version_spec}", "--user"]
        logging.info("Modül kuruluyor: %s", " ".join(command))
        subprocess.check_call(command, shell=False)
        try:
            importlib.import_module(module_info.mod_name)
            logging.info("Modül '%s' başarıyla kuruldu.", module_info.mod_name)
        except (ImportError, ModuleNotFoundError) as e:
            logging.error("Modül '%s' kurulmasına rağmen import edilemedi: %s", module_info.mod_name, e)
            raise

    @classmethod
    def manage_module(cls, module_info: "ModuleManager.ModuleInfo") -> None:
        if module_info.mod_name not in cls.ALLOWED_MODULES:
            raise ImportError(f"'{module_info.mod_name}' modülünün yüklenmesine izin verilmiyor.")
        try:
            mod = importlib.import_module(module_info.mod_name)
        except (ImportError, ModuleNotFoundError) as e:
            logging.error("Modül '%s' import edilemedi (%s). Kurulum deneniyor...", module_info.mod_name, e)
            cls.install_module(module_info)
            mod = importlib.import_module(module_info.mod_name)
        if CHECK_MODULE_UPDATES:
            if module_info.ver:
                installed_version = get_module_version(mod)
                if installed_version != module_info.ver:
                    logging.info("Modül '%s' sürümü (%s) gerekli (%s)'den farklı; yeniden kuruluyor.",
                                 module_info.mod_name, installed_version, module_info.ver)
                    cls.install_module(module_info)
            else:
                try:
                    logging.info("Modül '%s' güncelleniyor.", module_info.mod_name)
                    pkg_name = module_info.pkg if module_info.pkg else module_info.mod_name
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", pkg_name])
                except subprocess.CalledProcessError as e:
                    logging.error("Modül '%s' güncellemesi başarısız: %s", module_info.mod_name, e)

    @classmethod
    def ensure_required_modules(cls, modules: List["ModuleManager.ModuleInfo"]) -> None:
        for mod_info in modules:
            cls.manage_module(mod_info)

# ---------------------------------------------------------------------
# Gerekli modüllerin tanımlandığı liste
# ---------------------------------------------------------------------
required_modules: List[ModuleManager.ModuleInfo] = [
    ModuleManager.ModuleInfo("babel", "babel"),
    ModuleManager.ModuleInfo("certifi", "certifi"),
    ModuleManager.ModuleInfo("geopy", "geopy"),
    ModuleManager.ModuleInfo("hijridate", "hijridate"),
    ModuleManager.ModuleInfo("ntplib", "ntplib"),
    ModuleManager.ModuleInfo("pycountry", "pycountry"),
    ModuleManager.ModuleInfo("requests", "requests"),
    ModuleManager.ModuleInfo("rich", "rich"),
    ModuleManager.ModuleInfo("tzdata", "tzdata"),
    ModuleManager.ModuleInfo("dotenv", "python-dotenv"),
]

# ---------------------------------------------------------------------
# Global dinamik importlar
# ---------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ModuleManager.ensure_required_modules(required_modules)
    ast_mod = ModuleManager.dynamic_import("ast")
    asyncio = ModuleManager.dynamic_import("asyncio")
    babel = ModuleManager.dynamic_import("babel")
    babel_dates = ModuleManager.dynamic_import("babel.dates")
    collections_mod = ModuleManager.dynamic_import("collections")
    concurrent_futures = ModuleManager.dynamic_import("concurrent.futures")
    configparser = ModuleManager.dynamic_import("configparser")
    difflib = ModuleManager.dynamic_import("difflib")
    datetime_mod = ModuleManager.dynamic_import("datetime")
    datetime = datetime_mod.datetime
    timedelta = datetime_mod.timedelta
    timezone = datetime_mod.timezone
    geopy = ModuleManager.dynamic_import("geopy")
    hashlib = ModuleManager.dynamic_import("hashlib")
    hijridate = ModuleManager.dynamic_import("hijridate")
    locale = ModuleManager.dynamic_import("locale")
    messagebox = ModuleManager.dynamic_import("tkinter.messagebox")
    ntplib = ModuleManager.dynamic_import("ntplib")
    pycountry = ModuleManager.dynamic_import("pycountry")
    queue = ModuleManager.dynamic_import("queue")
    random = ModuleManager.dynamic_import("random")
    requests = ModuleManager.dynamic_import("requests")
    rich_logging = ModuleManager.dynamic_import("rich.logging")
    signal_mod = ModuleManager.dynamic_import("signal")
    simpledialog = ModuleManager.dynamic_import("tkinter.simpledialog")
    tk = ModuleManager.dynamic_import("tkinter")
    tkFont = ModuleManager.dynamic_import("tkinter.font")
    ttk = ModuleManager.dynamic_import("tkinter.ttk")
    types_mod = ModuleManager.dynamic_import("types")
    unicodedata = ModuleManager.dynamic_import("unicodedata")
    urllib_parse = ModuleManager.dynamic_import("urllib.parse")
    zoneinfo = ModuleManager.dynamic_import("zoneinfo")
    dotenv = ModuleManager.dynamic_import("dotenv")
    dotenv.load_dotenv()

def get_module_version(mod: types_mod.ModuleType) -> str:
    spec = getattr(mod, '__spec__', None)
    if spec is None or (hasattr(spec, 'origin') and spec.origin in ('built-in', 'frozen')):
        return "builtin"
    try:
        return importlib.metadata.version(mod.__name__.split('.')[0])
    except importlib.metadata.PackageNotFoundError:
        return getattr(mod, "__version__", "unknown")
    except Exception as e:
        logging.exception("Modül sürümü alınamadı: %s", e)
        return "unknown"

# ---------------------------------------------------------------------
# TkManager Sınıfı: Ana Tkinter örneğini merkezi olarak saklamak için
# ---------------------------------------------------------------------
class TkManager:
    main_instance: Optional[tk.Tk] = None
    _callback_queue = queue.Queue()

    @staticmethod
    def safe_after(delay: int, callback: Callable, *args, timeout: float = 10, run_in_thread: bool = True, context: str = "Unknown", **kwargs) -> Optional[str]:
        if TkManager.main_instance is None:
            logging.error(f"({context}) Main TK instance'ı mevcut değil (safe_after).")
            return None
        if threading.current_thread() is not threading.main_thread():
            cb_repr = repr(callback)
            logging.debug(f"safe_after: Queuing callback {cb_repr} [Context: {context}] from background thread {threading.get_ident()}")
            TkManager._callback_queue.put((callback, args, kwargs))
            return None
        cb_repr = repr(callback)
        if run_in_thread:
            logging.debug(f"safe_after: Scheduling callback {cb_repr} [Context: {context}] with delay {delay}ms to run in a background thread.")
        else:
            logging.debug(f"safe_after: Scheduling callback {cb_repr} [Context: {context}] with delay {delay}ms to run directly in main thread.")

        event = threading.Event()
        after_id = None

        def wrapper():
            nonlocal after_id
            log_prefix = f"safe_after wrapper (cb={cb_repr}, id={after_id}, context={context}):"
            logging.debug(f"{log_prefix} Starting execution (run_in_thread={run_in_thread}).")
            start_time = time.monotonic()
            if run_in_thread:
                def thread_func():
                    bg_log_prefix = f"{log_prefix} Background thread {threading.get_ident()}:"
                    try:
                        logging.debug(f"{bg_log_prefix} Starting work.")
                        callback(*args, **kwargs)
                        logging.debug(f"{bg_log_prefix} Finished work.")
                    except Exception as e_bg_cb:
                        logging.error(f"{bg_log_prefix} Exception during execution: {e_bg_cb}", exc_info=True)
                    finally:
                        event.set()
                threading.Thread(target=thread_func, daemon=True).start()
            else:
                try:
                    callback(*args, **kwargs)
                except Exception as e_cb:
                    logging.error(f"{log_prefix} Exception during callback execution: {e_cb}", exc_info=True)
                finally:
                    end_time = time.monotonic()
                    duration = end_time - start_time
                    logging.debug(f"{log_prefix} Finished execution (duration: {duration:.4f}s). Setting event.")
                    event.set()
        try:
            after_id = TkManager.main_instance.after(delay, wrapper)
            logging.debug(f"safe_after: Scheduled {cb_repr} [Context: {context}] with after_id {after_id}")
        except Exception as e_schedule:
            logging.error(f"safe_after: FAILED to schedule callback {cb_repr} [Context: {context}]. Error: {e_schedule}", exc_info=True)
            return None

        def watchdog():
            log_prefix_wd = f"safe_after watchdog (cb={cb_repr}, id={after_id}, context={context}):"
            logging.debug(f"{log_prefix_wd} Starting wait (timeout={timeout}s).")
            if not event.wait(timeout):
                logging.error(f"{log_prefix_wd} TIMEOUT! Callback did not complete in {timeout}s.")
                def cancel_callback():
                    log_prefix_cancel = f"safe_after watchdog cancel (cb={cb_repr}, id={after_id}, context={context}):"
                    try:
                        if TkManager.main_instance and TkManager.main_instance.winfo_exists():
                            TkManager.main_instance.after_cancel(after_id)
                            logging.info(f"{log_prefix_cancel} Callback cancelled via after_cancel.")
                        else:
                            logging.warning(f"{log_prefix_cancel} Cancellation skipped, main window doesn't exist.")
                    except tk.TclError as e_cancel:
                        logging.warning(f"{log_prefix_cancel} after_cancel failed (normal if callback finished just before cancel): {e_cancel}")
                    except Exception as e_generic_cancel:
                        logging.error(f"{log_prefix_cancel} Error during cancellation: {e_generic_cancel}", exc_info=True)
                if TkManager.main_instance and TkManager.main_instance.winfo_exists():
                    TkManager.safe_after(0, cancel_callback, context=f"Cancel-{context}-{after_id}", run_in_thread=False)
                else:
                     logging.warning(f"{log_prefix_wd} Cannot schedule cancellation, main window doesn't exist.")
            else:
                logging.debug(f"{log_prefix_wd} Event received, callback completed within timeout.")
        threading.Thread(target=watchdog, daemon=True).start()
        return after_id
    @staticmethod
    def process_callback_queue():
        while not TkManager._callback_queue.empty():
            try:
                cb, args, kwargs = TkManager._callback_queue.get_nowait()
            except queue.Empty:
                break
            except Exception as e_get:
                logging.error(f"Callback kuyruğundan öğe alınırken hata: {e_get}")
                continue
            try:
                cb(*args, **kwargs)
            except Exception as e_cb_exec:
                try:
                    cb_name = cb.__name__
                except AttributeError:
                    cb_name = repr(cb)
                logging.exception(f"Callback kuyruğundan '{cb_name}' yürütülürken hata: {e_cb_exec}")
        if TkManager.main_instance and TkManager.main_instance.winfo_exists():
            TkManager.main_instance.after(50, TkManager.process_callback_queue)
        else:
            logging.debug("process_callback_queue: Ana pencere yok, tekrar zamanlanmıyor.")

# ---------------------------------------------------------------------
# Dekoratörler: run_on_main_thread_global ve run_on_main_thread
# ---------------------------------------------------------------------
def run_on_main_thread_global(func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        if threading.current_thread() is threading.main_thread():
            return func(*args, **kwargs)
        else:
            if TkManager.main_instance is not None:
                result_container = []
                error_container = [] 
                event = threading.Event()
                def task():
                    try:
                        result_container.append(safe_invoke(func, *args, **kwargs))
                    except Exception as e_task:
                         error_container.append(e_task)
                         logging.error("Exception in task scheduled by run_on_main_thread_global for %s: %s", func.__name__, e_task, exc_info=True)
                    finally:
                        event.set() 
                schedule_success = TkManager.safe_after(
                    0,
                    task,
                    run_in_thread=False, 
                    context=f"run_on_main_thread_global:{func.__name__}"
                )
                if schedule_success is None:
                     logging.error("Failed to schedule task for %s via safe_after.", func.__name__)
                     return None 
                if not event.wait(timeout=10): 
                    logging.error("Timeout: %s fonksiyonu ana iş parçacığında çalıştırılırken kilitlendi veya zaman aşımına uğradı. (Mevcut thread: %s, Ana thread: %s)", func.__name__, threading.get_ident(), threading.main_thread().ident)
                    return None 
                if error_container:
                     logging.error("Function %s executed with error on main thread: %s", func.__name__, error_container[0])
                     return None 
                return result_container[0] if result_container else None
            else:
                logging.error("Main TK instance'ı mevcut değil: %s", func.__name__)
                return None
    return wrapper

def safe_invoke(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logging.exception("Callback %s sırasında beklenmeyen hata: %s", func.__name__, e)
        if threading.current_thread() is threading.main_thread():
            safe_showerror("Hata", f"Beklenmeyen bir hata oluştu: {e}")
        else:
            logging.error("GUI hata mesajı yalnızca ana iş parçacığında gösterilebilir. Hata: %s", e)

def run_on_main_thread(func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        try:
            view_instance = args[0] if args else None
            if threading.current_thread() != threading.main_thread():
                logging.warning("GUI fonksiyonu (%s) ana iş parçacığında çalıştırılmadı; yönlendiriliyor. (Mevcut thread: %s, Ana thread: %s)", func.__name__, threading.get_ident(), threading.main_thread().ident)
                if view_instance is not None and hasattr(view_instance, "pencere"):
                    if not hasattr(view_instance, "_pencere_lock") or view_instance._pencere_lock is None:
                         setattr(view_instance, "_pencere_lock", threading.RLock())
                    lock = view_instance._pencere_lock
                    with lock:
                        if view_instance.pencere is not None and view_instance.pencere.winfo_exists():
                            TkManager.safe_after(
                                0,
                                lambda: safe_invoke(func, *args, **kwargs),
                                run_in_thread=False,
                                context=f"run_on_main_thread:{func.__name__}"
                            )
                        else:
                            logging.error("Pencere nesnesi bulunamadı veya yok edildi, GUI güncellemesi (%s) yapılamıyor.", func.__name__)
                else:
                    logging.error("Pencere referansı (%s) için view instance bulunamadı.", func.__name__)
            else:
                return safe_invoke(func, *args, **kwargs)
        except Exception as e:
            logging.exception("GUI callback wrapper (%s) sırasında hata: %s", func.__name__, e)
    return wrapper

# ---------------------------------------------------------------------
# GUI Safe Wrapper Fonksiyonları
# ---------------------------------------------------------------------
@run_on_main_thread_global
def safe_showinfo(title: str, message: str, *args, **kwargs):
    return messagebox.showinfo(title, message, *args, **kwargs)

@run_on_main_thread_global
def safe_showerror(title: str, message: str, *args, **kwargs):
    return messagebox.showerror(title, message, *args, **kwargs)

@run_on_main_thread_global
def safe_askretrycancel(title: str, message: str, *args, **kwargs):
    return messagebox.askretrycancel(title, message, *args, **kwargs)

@run_on_main_thread_global
def safe_askyesno(title: str, message: str, *args, **kwargs):
    return messagebox.askyesno(title, message, *args, **kwargs)

@run_on_main_thread_global
def safe_askstring(title: str, prompt: str, *args, **kwargs) -> Optional[str]:
    return simpledialog.askstring(title, prompt, *args, **kwargs)

# ---------------------------------------------------------------------
# Diğer Yardımcı Fonksiyonlar
# ---------------------------------------------------------------------
def normalize_env_var(value):
    if isinstance(value, str):
        lowered = value.lower().strip()
        if lowered in ["false", "0", "no"]:
            return False
        elif lowered in ["true", "1", "yes"]:
            return True
    return value

ALLOWED_NODES = {
    ast_mod.Expression, ast_mod.Constant,
    ast_mod.Tuple, ast_mod.List, ast_mod.Dict, ast_mod.Set,
    ast_mod.UnaryOp, ast_mod.BinOp, ast_mod.BoolOp, ast_mod.Compare,
    ast_mod.Call, ast_mod.Load, ast_mod.keyword, ast_mod.Name, ast_mod.Attribute
}

ALLOWED_FUNCTIONS = {
    'abs': abs,
    'float': float,
    'int': int,
    'len': len,
    'max': max,
    'min': min,
    'messagebox.showinfo': safe_showinfo,
    'print': print,
    'str': str,
    'sum': sum,
    'tkMessageBox.showinfo': safe_showinfo,
}

def test_function():
    return "Test Fonksiyonu Çalıştı"

ALLOWED_FUNCTIONS['test'] = test_function

def safe_eval(expr):
    logging.info("safe_eval çağrıldı: %s", expr)
    if not isinstance(expr, str) or len(expr) > 100:
        raise ValueError("Geçersiz ifade")
    dev_mode = globals().get("DEVELOPER_MODE", False)
    if not str(dev_mode).lower() in ["true", "1", "yes"]:
        raise PermissionError("safe_eval yalnızca geliştirici modunda kullanılabilir.")
    try:
        parsed = ast_mod.parse(expr, mode='eval')
    except SyntaxError as se:
        raise ValueError(f"Geçersiz ifade: {expr}") from se
    for node in ast_mod.walk(parsed):
        if not isinstance(node, tuple(ALLOWED_NODES)):
            raise ValueError(f"İzin verilmeyen ifade tespit edildi: {ast_mod.dump(node)}")
        if isinstance(node, ast_mod.Call):
            if isinstance(node.func, ast_mod.Name):
                if node.func.id not in ALLOWED_FUNCTIONS:
                    raise ValueError(f"İzin verilmeyen fonksiyon çağrısı: {ast_mod.dump(node)}")
            elif isinstance(node.func, ast_mod.Attribute):
                if not (isinstance(node.func.value, ast_mod.Name) and node.func.value.id in ['messagebox', 'tkMessageBox'] and node.func.attr == 'showinfo'):
                    raise ValueError(f"İzin verilmeyen fonksiyon çağrısı: {ast_mod.dump(node)}")
            else:
                raise ValueError(f"İzin verilmeyen fonksiyon çağrısı: {ast_mod.dump(node)}")
    try:
        return ast_mod.literal_eval(parsed)
    except Exception:
        safe_globals = {'__builtins__': {}, 'messagebox': messagebox, 'tkMessageBox': messagebox}
        safe_globals.update(ALLOWED_FUNCTIONS)
        code = compile(parsed, "<safe_eval>", "eval")
        return eval(code, safe_globals, {})

# ---------------------------------------------------------------------
# ÖZEL EXCEPTION SINIFLARI ve diğer yardımcı fonksiyonlar
# ---------------------------------------------------------------------
class APIError(Exception):
    pass

class ConfigError(Exception):
    pass

class CommandExecutionError(Exception):
    pass

def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)

def retry_operation(
    operation: Callable[[], T],
    retries: int,
    backoff_factor: int,
    retryable_exceptions: Tuple[Type[Exception], ...] = (APIError, ConnectionError, TimeoutError)
) -> T:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            return operation()
        except retryable_exceptions as e:
            last_error = e
            sleep_time = min((backoff_factor ** attempt) * random.uniform(0.5, 1.5), 10)
            logging.warning(f"{attempt+1}. denemede geçici hata: {e}. {sleep_time:.2f} saniye sonra yeniden deneniyor.")
            time.sleep(sleep_time)
        except Exception as e:
            logging.exception("Retry operation sırasında yeniden denenemeyen istisna oluştu: %s", e)
            raise
    if last_error:
        raise last_error
    else:
        raise RuntimeError("Bilinmeyen hata oluştu.")

def get_timezone_from_str(tz_str: Optional[str]) -> timezone:
    if tz_str:
        try:
            return zoneinfo.ZoneInfo(tz_str)
        except zoneinfo.ZoneInfoNotFoundError as e:
            logging.warning("Zaman dilimi '%s' oluşturulamadı: %s. Sistem yerel zaman dilimi kullanılacak.", tz_str, e)
    return get_utc_now().astimezone().tzinfo or timezone.utc

CLEAN_TEXT_RE = re.compile(r'^[\s\u00A0\uFEFF\u200C]+|[\s\u00A0\uFEFF\u200C]+$')
GEOMETRY_RE = re.compile(r"^\d+x\d+(\+\-?\d+){2}$")
LOG_LEVEL_RE = re.compile(r"^\d{2}:\d{2}:\d{2} - (INFO|WARNING|ERROR|DEBUG) - |^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} - (INFO|WARNING|ERROR|DEBUG) - ")

def generate_cache_key(func_name: str, args: tuple, kwargs: Dict[str, Any]) -> str:
    current_date = get_utc_now().strftime('%Y-%m-%d')
    sorted_kwargs = tuple(sorted((k, v) for k, v in kwargs.items()))
    key_data = (func_name, args, sorted_kwargs, current_date)
    return hashlib.sha256(repr(key_data).encode('utf-8')).hexdigest()

def make_cache_decorator() -> Callable[[int], Callable[[Callable[..., T]], Callable[..., T]]]:
    def cache_result(ttl: int) -> Callable[[Callable[..., T]], Callable[..., T]]:
        cache: Dict[str, Tuple[Any, float]] = {}
        cache_lock = threading.RLock()
        MAX_CACHE_SIZE = 100
        stop_event = threading.Event()

        def cleanup_task():
            interval = min(ttl, 300)
            while not stop_event.wait(interval):
                with cache_lock:
                    now = time.time()
                    expired_keys = [k for k, (_, timestamp) in cache.items() if now - timestamp >= ttl]
                    for k in expired_keys:
                        del cache[k]
        cleanup_thread = threading.Thread(target=cleanup_task, daemon=True)
        cleanup_thread.start()

        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> T:
                key = generate_cache_key(func.__name__, args, kwargs)
                now = time.time()
                with cache_lock:
                    if key in cache:
                        result, timestamp = cache[key]
                        if now - timestamp < ttl:
                            logging.info(f"Önbellek kullanıldı: {func.__name__} (key: {key})")
                            return result
                        else:
                            del cache[key]
                result = func(*args, **kwargs)
                with cache_lock:
                    if len(cache) >= MAX_CACHE_SIZE:
                        oldest_key = next(iter(cache))
                        del cache[oldest_key]
                    cache[key] = (result, now)
                return result
            wrapper._cache = cache
            wrapper._cache_lock = cache_lock
            wrapper._cleanup_stop_event = stop_event
            wrapper._cleanup_thread = cleanup_thread
            return wrapper
        return decorator
    return cache_result

cache_result = make_cache_decorator()

# ---------------------------------------------------------------------
# UYGULAMA SINIFLARI: ConfigManager, IftarModel, IftarController, IftarView
# ---------------------------------------------------------------------
class ShortFilenameFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, style='%', max_length=30):
        super().__init__(fmt, datefmt, style)
        self.max_length = max_length
    def format(self, record):
        if len(record.filename) > self.max_length:
            record.filename = record.filename[:8] + "..." + record.filename[-8:]
        return super().format(record)

class ConfigManager:
    def __init__(self, path: str) -> None:
        self.path: str = path
        self.config: configparser.ConfigParser = configparser.ConfigParser()
        self.load()
    def load(self) -> None:
        if os.path.exists(self.path):
            try:
                try:
                    self.config.read(self.path, encoding="utf-8")
                except UnicodeDecodeError as e:
                    logging.error("Dosya encoding hatası: %s", e)
                    raise ConfigError(f"Ayar dosyası ({self.path}) UTF-8 formatında değil.")
                if "AYARLAR" not in self.config or not self.config["AYARLAR"]:
                    logging.info("Ayarlar bölümü eksik veya boş; varsayılan ayarlar yazılıyor.")
                    self.config["AYARLAR"] = {
                        "konum": "İzmir, Turkey",
                        "metod": "13",
                        "check_module_updates": "False",
                        "DEVELOPER_MODE": "False"
                    }
                    self.save()
            except ConfigError as ce:
                 logging.error("Yapılandırma hatası: %s", ce)
                 safe_showerror("Yapılandırma Hatası", str(ce))
                 self.config = configparser.ConfigParser()
                 self.config["AYARLAR"] = {
                     "konum": "İzmir, Turkey",
                     "metod": "13",
                     "check_module_updates": "False",
                     "DEVELOPER_MODE": "False"
                 }
            except (configparser.Error, OSError) as e:
                logging.exception("Ayarlar okunurken sorun oluştu: %s", e)
                try:
                    backup_path = self.path + f".backup_{int(time.time())}"
                    os.rename(self.path, backup_path)
                    logging.info("Bozuk ayar dosyası yedeklendi: %s", backup_path)
                except OSError as oe:
                    error_msg = (
                        f"Ayar dosyası yedeklenirken hata oluştu:\nHata Kodu: {oe.errno}\n"
                        f"Açıklama: {oe.strerror}\n\nLütfen dosya izinlerinizi kontrol edin veya uygulamayı yönetici olarak çalıştırın."
                    )
                    logging.exception("Bozuk ayar dosyası yedeklenemedi: %s", oe)
                    safe_showerror("Ayar Dosyası Yedekleme Hatası", error_msg)
                    raise ConfigError(f"Ayar dosyası yedeklenemedi: {oe.strerror}") from oe
                finally:
                    self.config = configparser.ConfigParser()
                    self.config["AYARLAR"] = {
                        "konum": "İzmir, Turkey",
                        "metod": "13",
                        "check_module_updates": "False",
                        "DEVELOPER_MODE": "False"
                    }
                    logging.info("Ayarlar sıfırlandı; varsayılan yapı yüklendi.")
        else:
            logging.info("Ayar dosyası bulunamadı; varsayılan ayarlar yükleniyor.")
            self.config["AYARLAR"] = {
                "konum": "İzmir, Turkey",
                "metod": "13",
                "check_module_updates": "False",
                "DEVELOPER_MODE": "False"
            }
            self.save()
    def get(self, key: str, default: str = "") -> str:
        return self.config["AYARLAR"].get(key, default)
    def set(self, key: str, value: str) -> None:
        self.config["AYARLAR"][key] = value
    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as configfile:
                self.config.write(configfile)
        except (OSError, configparser.Error) as e:
            logging.exception(f"Konfigürasyon kaydedilemedi: {e}")

class IftarModel:
    def __init__(self, base_dir: str, default_timeout: int, short_timeout: int, default_retries: int, backoff_factor: int) -> None:
        self.BASE_DIR: str = base_dir
        self.LOG_FILE: str = os.path.join(self.BASE_DIR, "activity.log")
        self.SETTINGS_PATH: str = os.path.join(self.BASE_DIR, "settings.ini")
        self.config_manager = ConfigManager(self.SETTINGS_PATH)
        self.DEVELOPER_MODE: bool = normalize_env_var(self.config_manager.get("DEVELOPER_MODE", "False"))
        self.DEFAULT_LOCATION: str = "İzmir, Turkey"
        self.DEFAULT_LATITUDE: float = 38.4237
        self.DEFAULT_LONGITUDE: float = 27.1428
        self.DEFAULT_METHOD: str = "13"
        self.current_location: str = ""
        self.current_latitude: Optional[float] = None
        self.current_longitude: Optional[float] = None
        self.current_method: str = ""
        self.current_country: str = ""
        self.log_buffer: queue.Queue = queue.Queue()
        self.DEVELOPER_MODE: bool = normalize_env_var(self.config_manager.get("DEVELOPER_MODE", "False"))
        self.DEFAULT_TIMEOUT: int = default_timeout
        self.SHORT_TIMEOUT: int = short_timeout
        self.DEFAULT_RETRIES: int = default_retries
        self.BACKOFF_FACTOR: int = backoff_factor
        self.GLOBAL_SESSION: requests.Session = requests.Session()
        self.GEOPY_USER_AGENT: str = "ezan_saatleri_v2"
        self.IPINFO_API_KEY: Optional[str] = os.getenv("IPINFO_API_KEY", "").strip()
        self._circuit_breaker_state = "closed"
        self._failure_count = 0
        self._failure_threshold = 3
        self._circuit_breaker_reset_timeout = 30
        self._circuit_breaker_open_until = 0.0
        self._circuit_breaker_lock = threading.Lock()
        max_workers = min(8, max(4, (os.cpu_count() or 1) * 2))
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.async_loop = None
        self.async_loop_ready = threading.Event()
        self.start_asyncio_loop()
        spec = importlib.util.find_spec("geopy")
        self.geolocator = geopy.geocoders.Nominatim(user_agent=self.GEOPY_USER_AGENT) if spec else None
        self.set_locale()
        self.setup_logging()
        self.set_excepthook()
        self._rate_limit_interval = 0.20
        self._last_api_call = 0.0
        self.initialize_settings()
        self._ezan_cache: Dict[Any, Dict[str, str]] = {}
        self._ezan_cache_lock = threading.RLock()
        self._ntp_cache: Optional[datetime] = None
        self._ntp_cache_time: float = 0.0
        self._ntp_lock = threading.RLock()
        self.emojiler: List[str] = ["🌙", "🌅", "☀️", "⛅", "🌆", "🌃"]
    def start_asyncio_loop(self) -> None:
        if self.async_loop and not self.async_loop.is_closed():
            logging.info("Async loop zaten çalışıyor.")
            return
        try:
            if self.async_loop:
                self._cleanup_async_loop()
            self.async_loop = asyncio.new_event_loop()
            self.async_loop_ready.clear()
            self.async_loop_thread = threading.Thread(
                target=self._run_loop,
                daemon=True
            )
            self.async_loop_thread.start()
            if self.async_loop_ready.wait(timeout=5):
                logging.info("Async loop başlatıldı.")
            else:
                logging.error("Async loop başlatılamadı. Reset mekanizması devreye giriyor.")
                self._cleanup_async_loop()
                time.sleep(1)
                self.start_asyncio_loop()
        except Exception as e:
            logging.exception("Async loop başlatılırken hata: %s", e)
            self._cleanup_async_loop()
            time.sleep(1)
            self.start_asyncio_loop()
    def _cleanup_async_loop(self):
        if not self.async_loop:
            return
        try:
            if self.async_loop.is_closed():
                logging.debug("Async loop zaten kapalı")
                return
            async def _cancel_and_shutdown():
                current_task = asyncio.current_task()
                pending = [t for t in asyncio.all_tasks() if t is not current_task]
                if pending:
                    logging.info("%d adet bekleyen task iptal ediliyor...", len(pending))
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    alive_tasks = [t for t in pending if not t.done()]
                    if alive_tasks:
                        logging.warning("%d task hala çalışıyor", len(alive_tasks))
                await self.async_loop.shutdown_asyncgens()
                if hasattr(self.async_loop, 'shutdown_default_executor'):
                    await self.async_loop.shutdown_default_executor()
            future = asyncio.run_coroutine_threadsafe(_cancel_and_shutdown(), self.async_loop)
            try:
                future.result(timeout=5)
            except concurrent.futures.TimeoutError:
                logging.error("Async cleanup işlemi zaman aşımına uğradı!")
            except Exception as e:
                logging.exception("Async cleanup sırasında beklenmeyen hata: %s", e)
            self.async_loop.call_soon_threadsafe(self.async_loop.stop)
        except Exception as e:
            logging.exception("Async loop cleanup sırasında kritik hata: %s", e)
        finally:
            if getattr(self, 'async_loop_thread', None):
                try:
                    self.async_loop_thread.join(timeout=5)
                    if self.async_loop_thread.is_alive():
                        logging.warning("Async loop thread hala çalışıyor! Resource leak riski!")
                    else:
                        logging.info("Async loop thread sorunsuz sonlandı")
                except Exception as e:
                    logging.exception("Thread join hatası: %s", e)
                finally:
                    self.async_loop_thread = None
            if self.async_loop and not self.async_loop.is_closed():
                try:
                    self.async_loop.close()
                    logging.info("Async loop başarıyla kapatıldı")
                except RuntimeError as e:
                    logging.warning("Loop zaten kapatılmış: %s", e)
                except Exception as e:
                    logging.exception("Loop kapatılırken bilinmeyen hata: %s", e)
                finally:
                    self.async_loop = None
    def _run_loop(self) -> None:
        try:
            asyncio.set_event_loop(self.async_loop)
            self.async_loop_ready.set()
            self.async_loop.run_forever()
        except Exception as e:
            logging.exception("Async loop çalışırken hata oluştu: %s", e)
            self._cleanup_async_loop()
            time.sleep(1)
            self.start_asyncio_loop()
    async def run_in_executor(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self.executor, functools.partial(func, *args, **kwargs))
        except Exception as e:
            logging.exception("Executor hatası: %s", e)
            raise
    def setup_logging(self) -> None:
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        log_queue = queue.Queue(-1)
        from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener
        queue_handler = QueueHandler(log_queue)
        queue_handler.setLevel(logging.INFO)
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.handlers = []
        logger.addHandler(queue_handler)
        file_handler = RotatingFileHandler(self.LOG_FILE, mode="a", maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_format_str = "%(asctime)s - %(levelname)s - %(message)s [%(filename)s:%(lineno)d]"
        file_formatter = ShortFilenameFormatter(fmt=file_format_str, datefmt="%Y-%m-%d %H:%M:%S", style='%', max_length=30)
        file_handler.setFormatter(file_formatter)
        destination_handlers = [file_handler]
        rich_formatter = None
        try:
            rich_console = ModuleManager.dynamic_import("rich.console").Console(file=original_stdout or io.StringIO(), force_terminal=True, color_system="auto")
            rich_handler = rich_logging.RichHandler(
                level=logging.INFO,
                show_time=False,
                show_path=False,
                rich_tracebacks=True,
                console=rich_console
            )
            rich_format_str = "%(asctime)s - %(levelname)s - %(message)s [Line:%(lineno)d]"
            rich_formatter = logging.Formatter(rich_format_str, datefmt="%H:%M:%S")
            rich_handler.setFormatter(rich_formatter)
            destination_handlers.append(rich_handler)
        except ImportError:
            logging.warning("Rich kütüphanesi bulunamadı veya yüklenemedi. Terminal çıktısı renksiz olacak.")
        except Exception as e:
            logging.error("RichHandler kurulurken hata oluştu: %s", e)
        buffer_handler = LogBufferHandler(self)
        buffer_formatter = rich_formatter if rich_formatter else file_formatter
        buffer_handler.setFormatter(buffer_formatter)
        destination_handlers.append(buffer_handler)
        self.log_queue_listener = QueueListener(log_queue, *destination_handlers)
        self.log_queue_listener.start()
        sys.stdout = StreamToLogger(logger, logging.INFO)
        sys.stderr = StreamToLogger(logger, logging.ERROR)
        logging.info("--- Loglama sistemi başlatıldı ---")
        logging.info("stdout artık loglama sistemine yönlendirildi.")
        if 'sys.stderr' in locals() and isinstance(sys.stderr, StreamToLogger):
            logging.info("stderr artık loglama sistemine yönlendirildi.")
    def log_to_file(self, message: str) -> None:
        logging.info(message)
    def set_locale(self) -> None:
        try:
            locale.setlocale(locale.LC_TIME, 'tr_TR.UTF-8')
        except locale.Error:
            try:
                locale.setlocale(locale.LC_TIME, 'Turkish_Turkey.1254')
            except locale.Error:
                logging.warning("Türkçe yerel ayar ayarlanamadı. Varsayılan ayar kullanılacak.")
    def my_excepthook(self, exc_type: type[BaseException], exc_value: BaseException, exc_tb: Optional[types_mod.TracebackType]) -> None:
        hata_mesaji = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        self.log_message(f"HATA: {hata_mesaji}\nLütfen log dosyasını kontrol ediniz.")
    def set_excepthook(self) -> None:
        sys.excepthook = self.my_excepthook
    def log_message(self, message: str) -> None:
        logging.info(message)
    def clear_log_file(self) -> None:
        try:
            with open(self.LOG_FILE, 'w', encoding='utf-8') as f:
                f.write("")
        except OSError as e:
            logging.exception("Log dosyası temizlenirken sorun oluştu: %s", e)
        while not self.log_buffer.empty():
            self.log_buffer.get()
    def initialize_settings(self) -> None:
        self.current_location = self.config_manager.get("konum", "")
        self.current_method = self.config_manager.get("metod", "")
        if self.current_location:
            coords = self.konum_bilgisini_al()
            if coords:
                self.current_latitude, self.current_longitude = coords
            else:
                self.current_location = self.DEFAULT_LOCATION
                self.current_latitude, self.current_longitude = self.DEFAULT_LATITUDE, self.DEFAULT_LONGITUDE
        else:
            try:
                future = self.executor.submit(self.otomatik_konum_bul)
                new_location, lat, lon = future.result(timeout=self.SHORT_TIMEOUT)
            except Exception as e:
                logging.exception("Otomatik konum alınamadı: %s", e)
                new_location, lat, lon = (None, None, None)
            if new_location:
                self.current_location = new_location
                self.current_latitude, self.current_longitude = lat, lon
            else:
                self.current_location = self.DEFAULT_LOCATION
                self.current_latitude, self.current_longitude = self.DEFAULT_LATITUDE, self.DEFAULT_LONGITUDE
        if not self.current_method:
            self.current_method = self.DEFAULT_METHOD
    @staticmethod
    def remove_diacritics(s: str) -> str:
        return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    @staticmethod
    def clean_text(text: str) -> str:
        return CLEAN_TEXT_RE.sub('', text)
    def format_active_location(self, lat: float, lon: float) -> str:
        if not self.geolocator:
            return f"{lat:.2f}°, {lon:.2f}° (Geopy bulunamadı)"
        try:
            location = self.geolocator.reverse(f"{lat}, {lon}", language='en', timeout=5)
            if location and location.address:
                return location.address
            else:
                return f"{lat:.2f}°, {lon:.2f}°"
        except Exception as e:
            logging.exception("Konum formatlanırken hata: %s", e)
        return f"{lat:.2f}°, {lon:.2f}°"
    def konum_bilgisini_al(self) -> Optional[tuple]:
        try:
            if not self.geolocator:
                self.log_message("Geopy kütüphanesi yüklü değil; varsayılan konum (İzmir, Turkey) kullanılıyor.")
                return (self.DEFAULT_LATITUDE, self.DEFAULT_LONGITUDE)
            self.log_message(f"Konum sorgusu: {self.current_location}")
            location = self.geolocator.geocode(self.current_location, timeout=5)
            if location:
                self.current_latitude, self.current_longitude = location.latitude, location.longitude
                self.log_message(f"Konum bulundu: {location.address} ({self.current_latitude}, {self.current_longitude})")
                return (self.current_latitude, self.current_longitude)
            else:
                self.log_message("Belirtilen konum bulunamadı.")
                return None
        except Exception as e:
            logging.exception("Konum sorgulaması sırasında sorun: %s", e)
            return None
    def otomatik_konum_bul(self) -> tuple:
        try:
            if not self.geolocator:
                self.log_message("Geopy kütüphanesi yüklü değil; otomatik konum alınamıyor.")
                return (None, None, None)
            self.log_message("Otomatik konum sorgusu başlatılıyor...")
            params = {}
            if self.IPINFO_API_KEY:
                params["token"] = self.IPINFO_API_KEY
            url = "https://ipinfo.io/json" + (("?" + urllib_parse.urlencode(params)) if params else "")
            response = self.perform_request_with_retry(url, retries=3, timeout=self.SHORT_TIMEOUT)
            self.log_message(f"ipinfo.io yanıt kodu: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                ip_country = data.get("country", "")
                self.current_country = ip_country
                location_str = data.get("loc", "")
                if location_str:
                    location_parts = location_str.split(",")
                    if len(location_parts) == 2:
                        lat = float(location_parts[0])
                        lon = float(location_parts[1])
                        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                            raise APIError("API tarafından döndürülen koordinatlar geçersiz.")
                        location_obj = self.geolocator.reverse(f"{lat}, {lon}", timeout=5)
                        if location_obj:
                            self.log_message(f"Otomatik konum bulundu: {location_obj.address}")
                            return (location_obj.address, lat, lon)
            self.log_message("Otomatik konum alınamadı.")
        except Exception as e:
            logging.exception("Otomatik konum sorgulaması sırasında sorun: %s", e)
        return (None, None, None)
    def ezan_saatlerini_hesapla(self, enlem: float, boylam: float, method: str) -> Optional[Dict[str, str]]:
        try:
            date_str = get_utc_now().strftime('%d-%m-%Y')
            params = {"latitude": enlem, "longitude": boylam, "method": method}
            url = "https://api.aladhan.com/v1/timings/" + date_str + "?" + urllib_parse.urlencode(params)
            response = self.perform_request_with_retry(url, retries=3, timeout=self.DEFAULT_TIMEOUT)
            data = response.json()
            if not isinstance(data, dict) or "data" not in data or not isinstance(data.get("data"), dict) or "timings" not in data["data"]:
                error_msg = "API'den geçersiz veya beklenmeyen formatta veri alındı."
                logging.error(error_msg + f" Alınan veri: {str(data)[:200]}...")
                raise APIError(error_msg)
            return {k.lower(): v for k, v in data["data"]["timings"].items()}
        except requests.exceptions.ConnectionError as e:
            logging.error("Bağlantı hatası: %s", e)
            if hasattr(self, "view") and self.view:
                 TkManager.safe_after(0, lambda: self.view.show_error("Bağlantı Hatası", "Sunucuya bağlanılamadı. Lütfen internet bağlantınızı kontrol edin."))
            return None
        except requests.exceptions.Timeout as e:
            logging.error("Zaman aşımı hatası: %s", e)
            if hasattr(self, "view") and self.view:
                TkManager.safe_after(0, lambda: self.view.show_error("Zaman Aşımı Hatası", "Sunucudan yanıt alınamadı. Lütfen daha sonra tekrar deneyin."))
            return None
        except requests.exceptions.RequestException as e:
            logging.exception("Ezan saatleri alınamadı: %s", e)
            if hasattr(self, "view") and self.view:
                 TkManager.safe_after(0, lambda: self.view.show_error("Ağ Hatası", "Ezan saatleri alınırken bir ağ sorunu oluştu."))
            return None
        except APIError as e:
            if hasattr(self, "view") and self.view:
                TkManager.safe_after(0, lambda: self.view.show_error("API Hatası", str(e)))
            return None
        except Exception as e:
            logging.exception("Ezan saatleri işlenirken beklenmeyen bir hata oluştu: %s", e)
            if hasattr(self, "view") and self.view:
                 TkManager.safe_after(0, lambda: self.view.show_error("İç Hata", "Ezan saatleri işlenirken beklenmeyen bir sorun oluştu."))
            return None
    def ramazan_tarihlerini_al(self) -> tuple:
        now = get_utc_now()
        yil = now.year
        url = f"https://api.aladhan.com/v1/gToHCalendar/{yil}/9"
        self.log_message(f"Ramazan tarihleri sorgusu: {url}")
        try:
            response = self.perform_request_with_retry(url, retries=3, timeout=self.DEFAULT_TIMEOUT)
            self.log_message(f"Ramazan API yanıt kodu: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                if "data" in data and isinstance(data["data"], list) and len(data["data"]) >= 30:
                    ramazan_baslangic = datetime.strptime(data["data"][0]["gregorian"]["date"], "%d-%m-%Y")
                    ramazan_bitis = datetime.strptime(data["data"][29]["gregorian"]["date"], "%d-%m-%Y")
                    return (ramazan_baslangic, ramazan_bitis)
                else:
                    self.log_message("Ramazan tarihleri beklenmeyen veri yapısı içeriyor.")
                    return (None, None)
            else:
                self.log_message("Ramazan tarihleri alınamadı.")
                return (None, None)
        except Exception as e:
            logging.exception("Ramazan tarihleri alınamadı: %s", e)
            return (None, None)
    def ramazan_mi(self) -> bool:
        try:
            now = get_utc_now()
            date_str = now.strftime('%d-%m-%Y')
            params = {"latitude": self.current_latitude, "longitude": self.current_longitude, "method": self.current_method}
            url = "https://api.aladhan.com/v1/timings/" + date_str + "?" + urllib_parse.urlencode(params)
            self.log_message(f"Ramazan kontrol sorgusu: {url}")
            response = self.perform_request_with_retry(url, retries=3, timeout=self.DEFAULT_TIMEOUT)
            self.log_message(f"Ramazan kontrol yanıt kodu: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            return int(data["data"]["date"]["hijri"]["month"]["number"]) == 9
        except Exception as e:
            logging.exception("Ramazan olup olmadığı belirlenemedi: %s", e)
            return False
    def hicri_tarih_header(self) -> str:
        today = get_utc_now()
        date_str = today.strftime("%d-%m-%Y")
        params = {"date": date_str, "adjustment": 0}
        url = "https://api.aladhan.com/v1/gToH?" + urllib_parse.urlencode(params)
        self.log_message(f"Hicri tarih sorgusu: {url}")
        try:
            response = self.perform_request_with_retry(url, retries=3, timeout=self.DEFAULT_TIMEOUT)
            self.log_message(f"Hicri tarih API yanıt kodu: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            hicri_gun = data["data"]["hijri"]["day"]
            hicri_yil = data["data"]["hijri"]["year"]
            try:
                ay_no = int(data["data"]["hijri"]["month"]["number"])
            except Exception:
                ay_no = None
            hicri_ay_isimleri = [
                "Muharrem", "Safer", "Rebiülevvel", "Rebiülahir",
                "Cemaziyelevvel", "Cemaziyelahir", "Recep", "Şaban",
                "Ramazan", "Şevval", "Zilkade", "Zilhicce"
            ]
            if isinstance(ay_no, int) and 1 <= ay_no <= 12:
                turkce_ay = hicri_ay_isimleri[ay_no - 1]
            else:
                hicri_ay_ing = data["data"]["hijri"]["month"]["en"].strip()
                normalized_ay = self.remove_diacritics(hicri_ay_ing).lower()
                ay_isimleri = {
                    "muharram": "Muharrem",
                    "safar": "Safer",
                    "rabi' al-awwal": "Rebiülevvel",
                    "rabi' al-thani": "Rebiülahir",
                    "jumada al-awwal": "Cemaziyelevvel",
                    "jumada al-thani": "Cemaziyelahir",
                    "rajab": "Recep",
                    "sha'ban": "Şaban",
                    "ramadan": "Ramazan",
                    "shawwal": "Şevval",
                    "dhu al-qi'dah": "Zilkade",
                    "dhu al-hijjah": "Zilhicce"
                }
                turkce_ay = ay_isimleri.get(normalized_ay, hicri_ay_ing)
            return f"{hicri_gun} {turkce_ay} {hicri_yil} İmsak Takvimi"
        except Exception as e:
            if getattr(self, "DEVELOPER_MODE", False):
                logging.exception("Hicri tarih bilgileri alınamadı: %s", e)
            else:
                logging.warning("Hicri tarih bilgileri alınamadı: %s", e)
            try:
                hijri_date = hijridate.Gregorian(today.year, today.month, today.day).to_hijri()
                hicri_gun = hijri_date.day
                hicri_ay = hijri_date.month
                hicri_yil = hijri_date.year
            except Exception as conv_e:
                logging.exception("Hijri tarih hesaplanamadı: %s", conv_e)
                return "İmsak Takvimi"
            hicri_ay_isimleri = [
                "Muharrem", "Safer", "Rebiülevvel", "Rebiülahir",
                "Cemaziyelevvel", "Cemaziyelahir", "Recep", "Şaban",
                "Ramazan", "Şevval", "Zilkade", "Zilhicce"
            ]
            hicri_ay_adi = hicri_ay_isimleri[hicri_ay - 1] if 1 <= hicri_ay <= 12 else str(hicri_ay)
            return f"{hicri_gun} {hicri_ay_adi} {hicri_yil} İmsak Takvimi"
    def get_current_hijri_month(self) -> Optional[int]:
        today = get_utc_now().astimezone()
        date_str = today.strftime("%d-%m-%Y")
        url = f"https://api.aladhan.com/v1/gToH?date={date_str}"
        try:
            response = self.perform_request_with_retry(url, retries=3, timeout=self.DEFAULT_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                return int(data["data"]["hijri"]["month"]["number"])
        except Exception as e:
            if getattr(self, "DEVELOPER_MODE", False):
                logging.exception("Hicri ay bilgileri alınamadı: %s", e)
            else:
                logging.warning("Hicri ay bilgileri alınamadı: %s", e)
            try:
                hijri_date = hijridate.Gregorian(today.year, today.month, today.day).to_hijri()
                return int(hijri_date.month)
            except Exception as conv_e:
                logging.exception("Hijri ay hesaplanamadı: %s", conv_e)
        return None
    def imsakiye_takvimini_al(self) -> List[List[str]]:
        now = get_utc_now().astimezone()
        location_parts = [part.strip() for part in self.current_location.split(',')]
        country = self.current_country if self.current_country else (location_parts[1] if len(location_parts) > 1 else "")
        current_year = now.year
        current_month = now.month
        if current_month == 12:
            next_year = current_year + 1
            next_month = 1
        else:
            next_year = current_year
            next_month = current_month + 1
        params_current = {
            "city": location_parts[0],
            "country": country,
            "method": self.current_method,
            "month": current_month,
            "year": current_year
        }
        url_current = "https://api.aladhan.com/v1/calendarByCity?" + urllib_parse.urlencode(params_current)
        self.log_message(f"İmsak takvimi sorgusu (Mevcut ay): {url_current}")
        params_next = {
            "city": location_parts[0],
            "country": country,
            "method": self.current_method,
            "month": next_month,
            "year": next_year
        }
        url_next = "https://api.aladhan.com/v1/calendarByCity?" + urllib_parse.urlencode(params_next)
        self.log_message(f"İmsak takvimi sorgusu (Sonraki ay): {url_next}")
        data_combined = []
        try:
            response_current = self.perform_request_with_retry(url_current, retries=3, timeout=self.DEFAULT_TIMEOUT)
            if response_current.status_code == 200:
                data_current = response_current.json()
                if "data" in data_current:
                    data_combined.extend(data_current["data"])
            response_next = self.perform_request_with_retry(url_next, retries=3, timeout=self.DEFAULT_TIMEOUT)
            if response_next.status_code == 200:
                data_next = response_next.json()
                if "data" in data_next:
                    data_combined.extend(data_next["data"])
        except Exception as e:
            logging.exception("İmsak takvimi alınamadı: %s", e)
            return []
        takvim: List[List[str]] = []
        mevcut_hicri_ay = self.get_current_hijri_month()
        if mevcut_hicri_ay is None:
            self.log_message("Hicri ay bilgileri alınamadı; tüm günler listelenecek.")
        try:
            data_combined.sort(key=lambda gun: datetime.strptime(gun["date"]["gregorian"]["date"], "%d-%m-%Y"))
        except Exception as e:
            logging.exception("Tarih sıralama hatası: %s", e)
        for gun in data_combined:
            gun_tarihi = datetime.strptime(gun["date"]["gregorian"]["date"], "%d-%m-%Y")
            if gun_tarihi.date() < now.date():
                continue
            if mevcut_hicri_ay is not None:
                gun_hicri_ay = int(gun["date"]["hijri"]["month"]["number"])
                if gun_hicri_ay != mevcut_hicri_ay:
                    continue
            tarih = babel_dates.format_date(gun_tarihi, "d MMMM yyyy EEEE", locale='tr_TR')
            imsak = gun["timings"]["Fajr"][:5]
            gunes = gun["timings"]["Sunrise"][:5]
            ogle = gun["timings"]["Dhuhr"][:5]
            ikindi = gun["timings"]["Asr"][:5]
            aksam = gun["timings"]["Maghrib"][:5]
            yatsi = gun["timings"]["Isha"][:5]
            takvim.append([tarih, imsak, gunes, ogle, ikindi, aksam, yatsi])
        if not takvim and data_combined:
            for gun in data_combined:
                gun_tarihi = datetime.strptime(gun["date"]["gregorian"]["date"], "%d-%m-%Y")
                if gun_tarihi.date() < now.date():
                    continue
                tarih = babel_dates.format_date(gun_tarihi, "d MMMM yyyy EEEE", locale='tr_TR')
                imsak = gun["timings"]["Fajr"][:5]
                gunes = gun["timings"]["Sunrise"][:5]
                ogle = gun["timings"]["Dhuhr"][:5]
                ikindi = gun["timings"]["Asr"][:5]
                aksam = gun["timings"]["Maghrib"][:5]
                yatsi = gun["timings"]["Isha"][:5]
                takvim.append([tarih, imsak, gunes, ogle, ikindi, aksam, yatsi])
        self.log_message("İmsak takvimi alındı.")
        return takvim
    def ntp_time_kontrol(self) -> Optional[datetime]:
        now_ts = time.time()
        with self._ntp_lock:
            if self._ntp_cache is not None and (now_ts - self._ntp_cache_time < 30):
                return self._ntp_cache
        try:
            c = ntplib.NTPClient()
            response = c.request('pool.ntp.org', version=3, timeout=3)
            ntp_time = datetime.fromtimestamp(response.tx_time, tz=timezone.utc)
        except Exception as e:
            logging.exception("Sistem saati kontrolü yapılamadı: %s", e)
            return None
        now_ts_after = time.time()
        with self._ntp_lock:
            if self._ntp_cache is not None and (now_ts_after - self._ntp_cache_time < 30):
                return self._ntp_cache
            self._ntp_cache = ntp_time
            self._ntp_cache_time = now_ts_after
        return ntp_time
    def sistem_saati_kontrol_alternative(self) -> tuple:
        try:
            self.log_message("NTP bağlantısı deneniyor... ⏳")
            ntp_time = self.ntp_time_kontrol()
            if ntp_time is None:
                self.log_message("NTP bağlantısı başarısız.")
                return ("❌", "NTP bağlantısı başarısız")
            sys_time = get_utc_now()
            fark_saniye = abs((ntp_time - sys_time).total_seconds())
            local_time = sys_time.astimezone()
            ntp_tarih = ntp_time.astimezone(local_time.tzinfo).date()
            local_tarih = local_time.date()
            gun_farki = (local_tarih - ntp_tarih).days
            if abs(gun_farki) == 1:
                tarih_durumu = "Doğru ✅ (Saat Dilimi Farkı)"
            elif gun_farki == 0:
                tarih_durumu = "Doğru ✅"
            else:
                tarih_durumu = "FARKLI GÜN ❌"
            self.log_message(f"NTP Sunucu Saati: {ntp_time.strftime('%Y-%m-%d %H:%M:%S')}, Bilgisayar UTC Saati: {sys_time.strftime('%Y-%m-%d %H:%M:%S')}, Fark: ±{fark_saniye:.2f} saniye, Tarih: {tarih_durumu}")
            if fark_saniye > 60 or "❌" in tarih_durumu:
                self.log_message("Bilgisayar saati güncel değil.")
                return ("❌", "Saat güncel değil!")
            else:
                self.log_message("Bilgisayar saati güncel.")
                return ("✅", "Güncel")
        except Exception as e:
            logging.exception("Sistem saati kontrolü yapılamadı: %s", e)
            return ("❌", "Sistem saati kontrol edilemedi")
    def api_canlılık_durumu(self) -> tuple:
        try:
            baslangic = time.time()
            url = "https://api.aladhan.com/v1/gToHCalendar/2023/9"
            response = self.perform_request_with_retry(url, retries=3, timeout=self.SHORT_TIMEOUT)
            gecen = int((time.time() - baslangic) * 1000)
            self.log_message(f"API sağlık kontrolü: {url} - {response.status_code} ({gecen} ms)")
            return ("api.aladhan.com", gecen)
        except Exception as e:
            logging.exception("API'den namaz vakitleri alınamadı: %s", e)
            return ("api.aladhan.com", f"bağlantısı başarısız: {e}")
    def run_async(self, func: Callable[..., None], *args: Any, **kwargs: Any) -> None:
        def thread_target() -> None:
            try:
                func(*args, **kwargs)
            except Exception as e:
                error_msg = traceback.format_exc()
                logging.exception("Asenkron fonksiyon çalıştırılırken sorun: %s", e)
                self.log_message(f"Asenkron fonksiyon hatası:\n{error_msg}")
        future = self.executor.submit(thread_target)
        def callback(fut: Any) -> None:
            try:
                result = fut.result(timeout=5)
            except concurrent.futures.TimeoutError as te:
                logging.error("Asenkron görev zaman aşımına uğradı: %s", te)
            except Exception as e:
                logging.exception("Asenkron görev başarısız: %s", e)
        future.add_done_callback(callback)
    def perform_request_with_retry(self, url: str, retries: Optional[int] = None, backoff_factor: Optional[int] = None, timeout: Optional[int] = None) -> requests.Response:
        if retries is None:
            retries = self.DEFAULT_RETRIES
        if backoff_factor is None:
            backoff_factor = self.BACKOFF_FACTOR
        if timeout is None:
            timeout = self.DEFAULT_TIMEOUT
        with self._circuit_breaker_lock:
            current_time = time.time()
            if self._circuit_breaker_state == "open" and current_time < self._circuit_breaker_open_until:
                logging.warning(
                    f"Circuit breaker şu anda açık. API çağrısı atlanıyor. Açık kalma süresi {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._circuit_breaker_open_until))} zamanına kadar devam edecek."
                )
                raise APIError("Circuit breaker açık. Hatalı uç noktalara aşırı istek gönderilmesini önlemek için API çağrısı atlanıyor.")
            elif self._circuit_breaker_state == "open" and current_time >= self._circuit_breaker_open_until:
                self._circuit_breaker_state = "half-open"
        def operation() -> requests.Response:
            time_since_last = time.time() - self._last_api_call
            if time_since_last < self._rate_limit_interval:
                time.sleep(self._rate_limit_interval - time_since_last)
            self._last_api_call = time.time()
            try:
                certifi = ModuleManager.dynamic_import("certifi")
                response = self.GLOBAL_SESSION.get(url, timeout=timeout, verify=certifi.where())
                response.raise_for_status()
            except requests.RequestException as e:
                with self._circuit_breaker_lock:
                    self._failure_count += 1
                    if self._failure_count >= self._failure_threshold:
                        self._circuit_breaker_state = "open"
                        self._circuit_breaker_open_until = time.time() + self._circuit_breaker_reset_timeout
                        logging.warning(
                            f"Arka arkaya {self._failure_count} başarısız deneme nedeniyle circuit breaker açıldı."
                            f"Açık kalma süresi {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._circuit_breaker_open_until))} zamanına kadar devam ediyor"
                            f"(yaklaşık {self._circuit_breaker_reset_timeout} saniye)."
                        )
                logging.exception("API isteği başarısız oldu. [Detaylar gizlendi]")
                raise APIError("API isteği başarısız oldu.") from e
            if not response.content:
                raise APIError("API'den boş veri alındı. Lütfen internet bağlantınızı kontrol edin.")
            content_type = (response.headers.get('Content-Type', '') or '').lower()
            if 'application/json' not in content_type:
                raise APIError("API, JSON formatında veri döndürmüyor. Lütfen API belgelerini kontrol edin.")

            raw_text = response.text or ""
            cleaned_text = CLEAN_TEXT_RE.sub("", raw_text)
            if not cleaned_text:
                raise APIError("API'den boş veri alındı. Lütfen internet bağlantınızı kontrol edin.")
            if cleaned_text != raw_text:
                try:
                    response._content = cleaned_text.encode(response.encoding or "utf-8")
                except Exception:
                    response._content = cleaned_text.encode("utf-8", errors="replace")
                    response.encoding = "utf-8"

            try:
                _ = response.json()
            except json.JSONDecodeError as je:
                if getattr(self, "DEVELOPER_MODE", False):
                    logging.exception("JSON decode hatası. [Detaylar gizlendi]")
                else:
                    logging.warning("JSON decode hatası. [Detaylar gizlendi]")
                raise APIError("Geçersiz JSON yanıtı alındı.") from je
            with self._circuit_breaker_lock:
                if self._circuit_breaker_state == "half-open":
                    self._circuit_breaker_state = "closed"
                    self._failure_count = 0
            return response
        try:
            result = retry_operation(operation, retries, backoff_factor)
            self.log_message(f"{url} adresine yapılan istek başarılı. Durum: {result.status_code}")
            return result
        except requests.RequestException as e:
            logging.exception("Hata: %s adresine yapılan istek %d denemede başarısız oldu. [Detaylar gizlendi]", url, retries)
            raise
    def show_about(self) -> None:
        imported_modules = {name: mod for name, mod in globals().items() if isinstance(mod, types_mod.ModuleType)}
        module_names = sorted(imported_modules.keys(), key=lambda n: n.lower())
        about_lines = []
        for name in module_names:
            mod = imported_modules[name]
            version_info = get_module_version(mod)
            about_lines.append(f"{name}: {version_info}")
        apiler = [
            "Namaz Vakitleri - api.aladhan.com",
            "Konum - ipinfo.io",
            "Sistem Saati - pool.ntp.org"
        ]
        about_text = "Yüklü kütüphaneler ve sürümleri:\n" + "\n".join(about_lines)
        about_text += "\n\nAPI Alan Adresleri:\n" + "\n".join(apiler)
        if hasattr(self, "view") and self.view:
            self.view.show_info(about_text)
        else:
            print(about_text)
    def run(self) -> None:
        if hasattr(self, "view") and self.view:
            self.view.run_iftar_app()

class LogBufferHandler(logging.Handler):
    def __init__(self, model: IftarModel) -> None:
        super().__init__()
        self.model = model
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.model.log_buffer.put(msg + "\n")
        except Exception as e:
            self.handleError(record)

class IftarController:
    def __init__(self, model: IftarModel) -> None:
        self.model: IftarModel = model
        self.view: Optional["IftarView"] = None
        self.resize_after_id: Optional[str] = None
    def set_view(self, view: "IftarView") -> None:
        self.view = view
    def log_message(self, message: str) -> None:
        self.model.log_message(message)
        if self.view:
            TkManager.safe_after(0, self.view.update_console_from_model, run_in_thread=False, context="Controller.log_message.update_console")
    def clear_log(self) -> None:
        self.model.clear_log_file()
        if self.view:
            self.view.clear_console_panel()
        if os.name == "nt":
            os.system("cls")
        else:
            os.system("clear")
        self.log_message("Konsol paneli ve terminal logları temizlendi.")
    def finalize_system_check(self) -> None:
        TkManager.safe_after(0, lambda: self.view.update_sistem_saati_label("⏳", "Kontrol ediliyor..."), run_in_thread=False, context="FinalizeSystemCheck-Start")
        def check_and_update():
            time.sleep(2)
            result_icon, result_msg = self.model.sistem_saati_kontrol_alternative()
            if self.view:
                TkManager.safe_after(0, lambda: self.view.update_sistem_saati_label(result_icon, result_msg), run_in_thread=False, context="FinalizeSystemCheck")
            self.log_message(f"Sistem Saati Kontrolü: {result_icon} {result_msg}")
        threading.Thread(target=check_and_update, daemon=True).start()
    def konum_guncelle(self) -> None:
        self.log_message("Otomatik konum güncelleme butonuna basıldı.")
        async def task_async() -> None:
            new_location, lat, lon = await self.model.run_in_executor(self.model.otomatik_konum_bul)
            if new_location:
                self.model.current_location = new_location
                self.model.current_latitude, self.model.current_longitude = lat, lon
                self.log_message(f"Konum güncellendi: {new_location}")
                if self.view and self.view.pencere:
                    TkManager.safe_after(0, lambda: safe_showinfo("Konum Güncellendi", f"Yeni konum: {new_location}"))
                    ezan_saatleri = await self.model.run_in_executor(self.model.ezan_saatlerini_hesapla, self.model.current_latitude, self.model.current_longitude, self.model.current_method)
                    imsakiye = await self.model.run_in_executor(self.model.imsakiye_takvimini_al)
                    logging.info("Yeni ezan saatleri: %s", ezan_saatleri)
                    logging.info("Yeni imsak takvimi: %s", imsakiye)
                    if not ezan_saatleri:
                        self.log_message("Yeni konum için ezan saatleri alınamadı; eski veriler kullanılacak.")
                    else:
                        self.view.current_ezan_saatleri = ezan_saatleri
                    TkManager.safe_after(500, lambda: (self.view.arayuzu_guncelle(self.view.current_ezan_saatleri), self.view.guncelle_takvim(imsakiye), self.view.Aktif_Konum_Labeli_uygulama_sagligi_icinde_widget_V2(), self.view.update_countdown()), run_in_thread=False, context="UpdateGUIAfterLocation")
        asyncio.run_coroutine_threadsafe(task_async(), self.model.async_loop)
    def suanki_konum_goster(self) -> None:
        if self.view:
            full_location = self.model.format_active_location(self.model.current_latitude, self.model.current_longitude)
            msg = f"Aktif Konum: {full_location}"
            self.view.show_info(msg)
    def metod_degistir(self) -> None:
        methods = {
            "2": "MWL (Muslim World League)",
            "4": "Egypt (Egyptian General Authority of Survey)",
            "5": "Mekke (Umm al-Qura, Mekke)",
            "7": "Tahran (Institute of Geophysics, University of Tehran)",
            "9": "Körfez Bölgesi",
            "10": "Kuveyt",
            "11": "Katar",
            "12": "ISNA (Islamic Society of North America)",
            "13": "Türkiye Diyanet",
            "15": "Jafari (Shia Ithna-Ashari, Leva Research Institute, Qum)"
        }
        method_window = tk.Toplevel(self.view.pencere)
        method_window.title("Hesaplama Yöntemi Seç")
        method_window.grab_set()
        method_window.focus_force()
        selected_method = tk.StringVar(value=self.model.current_method)
        for method_num, method_name in methods.items():
            is_selected = method_num == self.model.current_method
            emoji = " ✅" if is_selected else ""
            method_label = f"({method_num}) {method_name}{emoji}"
            rb = ttk.Radiobutton(method_window, text=method_label, value=method_num, variable=selected_method)
            rb.pack(anchor='w', padx=10, pady=2)
        def apply_method():
            choice = selected_method.get()
            if choice != self.model.current_method:
                self.model.current_method = choice
                self.log_message(f"Hesaplama yöntemi güncellendi: {methods[choice]}")
                self.view.show_info(f"Hesaplama yöntemi güncellendi: {methods[choice]}")
                ezan_saatleri = self.model.ezan_saatlerini_hesapla(
                    self.model.current_latitude,
                    self.model.current_longitude,
                    self.model.current_method
                )
                self.view.current_ezan_saatleri = ezan_saatleri
                self.view.arayuzu_guncelle(ezan_saatleri)
                self.view.update_countdown()
            method_window.destroy()
        ttk.Button(method_window, text="Uygula", command=apply_method).pack(pady=5)
        def close_window(event=None):
            method_window.destroy()
        method_window.protocol("WM_DELETE_WINDOW", close_window)
        method_window.bind("<Escape>", close_window)
        method_window.update_idletasks()
        w = method_window.winfo_width()
        h = method_window.winfo_height()
        ws = method_window.winfo_screenwidth()
        hs = method_window.winfo_screenheight()
        x = (ws // 2) - (w // 2)
        y = (hs // 2) - (h // 2)
        method_window.geometry(f'{w}x{h}+{x}+{y}')
    def show_about(self) -> None:
        imported_modules = {name: mod for name, mod in globals().items() if isinstance(mod, types_mod.ModuleType)}
        module_names = sorted(imported_modules.keys(), key=lambda n: n.lower())
        about_lines = []
        for name in module_names:
            mod = imported_modules[name]
            version_info = get_module_version(mod)
            about_lines.append(f"{name}: {version_info}")
        apiler = [
            "Namaz Vakitleri - api.aladhan.com",
            "Konum - ipinfo.io",
            "Sistem Saati - pool.ntp.org"
        ]
        about_text = f"Sürüm: {APP_VERSION}\n\nYüklü kütüphaneler ve sürümleri:\n" + "\n".join(about_lines)
        about_text += "\n\nAPI Alan Adresleri:\n" + "\n".join(apiler)
        if self.view:
            self.view.show_info(about_text)
        else:
            print(about_text)
    def run(self) -> None:
        if self.view:
            self.view.run_iftar_app()

class IftarView:
    def __init__(self, controller: IftarController, model: IftarModel) -> None:
        self.controller: IftarController = controller
        self.model: IftarModel = model
        self.pencere: Optional[tk.Tk] = None
        self.ConsolePanel: Optional[tk.Text] = None
        self.sistem_saati_label: Optional[tk.Label] = None
        self.default_font: Optional[tkFont.Font] = None
        self.bold_font: Optional[tkFont.Font] = None
        self.large_bold_font: Optional[tkFont.Font] = None
        self.button_font: Optional[tkFont.Font] = None
        self.vakit_cerceve: Optional[tk.Frame] = None
        self.resize_after_id: Optional[str] = None
        self.windowed_geometry: Optional[str] = None
        self.static_prefix = "📍 Aktif Konum: "
        self.dynamic_entry: Optional[tk.Entry] = None
        self.tooltip_window: Optional[tk.Toplevel] = None
        self.tooltip_after_id: Optional[str] = None
        self._last_configure_time: float = 0
        self._stored_selection: str = ""
        self.aktif_konum_frame: Optional[tk.Frame] = None
        self.current_ezan_saatleri: Dict[str, str] = {}
        self.sayac_label: Optional[tk.Label] = None
        self.yuzde_cubugu: Optional[ttk.Progressbar] = None
        self.yuzde_etiket: Optional[tk.Label] = None
        self.prayer_labels: Optional[List[tk.Widget]] = None
        self.prayer_time_labels: Optional[List[tk.Widget]] = None
        self.check_module_updates_var = None
        self._last_vakit_indices = None
    def toggle_module_update_check(self) -> None:
        new_val = self.check_module_updates_var.get()
        self.model.config_manager.set("check_module_updates", "True" if new_val else "False")
        self.model.config_manager.save()
        global CHECK_MODULE_UPDATES
        CHECK_MODULE_UPDATES = new_val
        self.controller.log_message(f"Açılışta modül güncellemeleri kontrol et: {'Aktif' if new_val else 'Pasif'}")
    def toggle_developer_mode(self) -> None:
        new_val = self.developer_mode_var.get()
        self.model.DEVELOPER_MODE = new_val
        self.model.config_manager.set("DEVELOPER_MODE", "True" if new_val else "False")
        self.model.config_manager.save()
        try:
            global DEVELOPER_MODE
            DEVELOPER_MODE = new_val
        except Exception:
            pass
        try:
            cp = self.ConsolePanel
            if cp and cp.winfo_exists():
                console_frame = cp.master.master
                if new_val:
                    try:
                        console_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
                    except Exception:
                        console_frame.pack(side="bottom", fill="x")
                    try:
                        self.update_console_from_model()
                    except Exception:
                        pass
                else:
                    console_frame.pack_forget()
        except Exception:
            pass
        try:
            if self.pencere and self.pencere.winfo_exists() and not self.pencere.attributes("-fullscreen"):
                geom = self.pencere.winfo_geometry()
                width_str, rest = geom.split("x")
                height_str, pos_str = rest.split("+", 1)
                width = int(width_str)
                x_offset, y_offset = map(int, pos_str.split("+"))
                target_h = 860 if new_val else 650
                self.pencere.geometry(f"{width}x{target_h}+{x_offset}+{y_offset}")
        except Exception:
            pass
        self.controller.log_message(f"Geliştirici Modu {'aktif' if new_val else 'pasif'} olarak güncellendi.")
    def store_selection(self, event: tk.Event) -> None:
        try:
            self._stored_selection = event.widget.selection_get()
        except tk.TclError:
            self._stored_selection = ""
    def store_full_location_data(self) -> str:
        if self.model.current_latitude is not None and self.model.current_longitude is not None:
            return self.model.format_active_location(self.model.current_latitude, self.model.current_longitude)
        else:
            return "❌ Konum alınamadı."
    def get_display_location_data(self) -> str:
        return self.store_full_location_data()
    def Aktif_Konum_Labeli_uygulama_sagligi_icinde_widget_V2(self) -> None:
        def get_country_flag(country_name: str) -> str:
            input_normalized = country_name.strip().lower()
            country_candidates = {}
            for country in pycountry.countries:
                country_candidates[country.name.lower()] = country.alpha_2.upper()
                if hasattr(country, 'official_name'):
                    country_candidates[country.official_name.lower()] = country.alpha_2.upper()
                if hasattr(country, 'common_name'):
                    country_candidates[country.common_name.lower()] = country.alpha_2.upper()
            best_matches = difflib.get_close_matches(input_normalized, country_candidates.keys(), n=1, cutoff=0.6)
            if best_matches:
                alpha_2 = country_candidates[best_matches[0]]
                return (chr(0x1F1E6 + ord(alpha_2[0]) - ord('A')) +
                        chr(0x1F1E6 + ord(alpha_2[1]) - ord('A')))
            return ""
        def heavy_task():
            city = ""
            country = ""
            if self.model.current_latitude is not None and self.model.current_longitude is not None:
                lat = self.model.current_latitude
                lon = self.model.current_longitude
                if self.model.geolocator:
                    try:
                        location = self.model.geolocator.reverse(f"{lat}, {lon}", language="en", timeout=5)
                        if location:
                            address_details = location.raw.get("address", {})
                            city = address_details.get("city") or address_details.get("state") or ""
                            if not city:
                                city = (address_details.get("town") or address_details.get("village") or
                                        address_details.get("municipality") or address_details.get("county") or "").strip()
                            else:
                                city = city.strip()
                            country = address_details.get("country", "").strip()
                        if not city and location and location.address:
                            parts = location.address.split(",")
                            if parts:
                                city = parts[0].strip()
                                country = parts[-1].strip() if len(parts) > 1 else ""
                    except Exception as e:
                        logging.exception("Ters geokodlama hatası: %s", e)
                else:
                    if self.model.current_location and "," in self.model.current_location:
                        parts = self.model.current_location.split(",")
                        city = parts[0].strip()
                        country = parts[-1].strip()
                flag = get_country_flag(country) if country else ""
                active_text = f"{city} {flag}: {self.model.current_latitude:.2f}° , {self.model.current_longitude:.2f}°"
            else:
                active_text = "Konum bilgisi yok"
            TkManager.safe_after(0, lambda: self._update_dynamic_entry(active_text))
        threading.Thread(target=heavy_task, daemon=True).start()
    def toggle_fullscreen(self, event: tk.Event = None) -> str:
        is_fullscreen = self.pencere.attributes("-fullscreen")
        if not is_fullscreen:
            self.windowed_geometry = self.pencere.geometry()
            self.pencere.attributes("-fullscreen", True)
        else:
            self.pencere.attributes("-fullscreen", False)
            if self.windowed_geometry:
                self.pencere.geometry(self.windowed_geometry)
        return "break"
    def _update_dynamic_entry(self, text: str) -> None:
        if self.dynamic_entry:
            clean_text = text.strip()
            self.dynamic_entry.config(state="normal", font=("Segoe UI Emoji", 10))
            self.dynamic_entry.delete(0, "end")
            self.dynamic_entry.insert(0, clean_text)
            self.dynamic_entry.config(state="readonly")
    def show_text_context_menu(self, event: tk.Event) -> None:
        widget = event.widget
        menu = tk.Menu(self.pencere, tearoff=0)
        menu.add_command(label="Kopyala", command=lambda: self.copy_text_from_widget(widget))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    def copy_text_from_widget(self, widget: tk.Widget) -> None:
        current_instance_id = id(widget)
        current_widget_type = type(widget).__name__
        log_prefix = f"[Patcher V3][Widget ID: {current_instance_id}, Type: {current_widget_type}]"
        logging.debug(f"{log_prefix} copy_text_from_widget başlatıldı (No Fallback).")
        text_to_copy = ""
        selection_attempted = False
        get_attempted = False
        selection_found = False
        label_get_success = False
        try:
            if isinstance(widget, (tk.Entry, tk.Text)):
                selection_attempted = True
                text_to_copy = widget.selection_get()
                selection_found = True
                logging.debug(f"{log_prefix} Selection found: '{text_to_copy}'")
            elif isinstance(widget, tk.Label):
                get_attempted = True
                text_to_copy = widget.cget("text")
                label_get_success = True
                logging.debug(f"{log_prefix} Label text got: '{text_to_copy}'")
        except tk.TclError:
            if selection_attempted:
                logging.warning(f"{log_prefix} selection_get() failed (No selection). NO FALLBACK.")
            else:
                logging.error(f"{log_prefix} TclError occurred, but selection wasn't attempted (check widget type or cget).")
        except Exception as e_outer:
            logging.error(f"{log_prefix} Error getting text: {e_outer}", exc_info=True)
            text_to_copy = ""
        text_determination_result = "Selection" if selection_found else ("LabelGet" if label_get_success else "Failed/NoSelection")
        logging.info(f"{log_prefix} Text determination result: {text_determination_result}. Final text to copy: '{text_to_copy}'")
        if text_to_copy:
            try:
                logging.info(f"{log_prefix} Attempting to copy to clipboard: '{text_to_copy}'")
                self.pencere.clipboard_clear()
                self.pencere.clipboard_append(text_to_copy)
                try:
                    clipboard_after = self.pencere.clipboard_get()
                    logging.debug(f"{log_prefix} Clipboard content after append (Verification): '{clipboard_after}'")
                    if clipboard_after == text_to_copy:
                        logging.info(f"{log_prefix} Clipboard verification PASSED.")
                    else:
                        logging.error(f"{log_prefix} !! Clipboard verification FAILED !! Expected: '{text_to_copy}', Got: '{clipboard_after}'")
                except Exception as e_verify:
                    logging.warning(f"{log_prefix} Clipboard verification check failed: {e_verify}")

            except Exception as e_clip:
                logging.error(f"{log_prefix} Clipboard operation failed: {e_clip}", exc_info=True)
                safe_showerror("Kopyalama Hatası", f"Panoya kopyalarken hata oluştu:\n{e_clip}")
        else:
            logging.warning(f"{log_prefix} No text determined/available to copy (selection failed/empty or Label empty/error).")

    def show_full_location_tooltip(self, event: tk.Event) -> None:
        x_root, y_root = event.x_root, event.y_root

        @run_on_main_thread
        def _display_tooltip_with_text(full_text: str, x: int, y: int):
            if not (self.pencere and self.pencere.winfo_exists()): return
            if self.tooltip_window and self.tooltip_window.winfo_exists():
                try:
                    self.tooltip_window.destroy()
                except tk.TclError:
                    pass
            self.tooltip_window = None
            try:
                self.tooltip_window = tk.Toplevel(self.pencere)
                self.tooltip_window.overrideredirect(True)
                font_to_use = self.default_font if hasattr(self, 'default_font') else None
                label = ttk.Label(self.tooltip_window, text=full_text, background="#FFFFE0", relief="solid", borderwidth=1, font=font_to_use, padding=(3, 1))
                label.pack()
                self.tooltip_window.update_idletasks()
                tooltip_width = self.tooltip_window.winfo_reqwidth()
                tooltip_height = self.tooltip_window.winfo_reqheight()
                screen_width = self.pencere.winfo_screenwidth()
                screen_height = self.pencere.winfo_screenheight()
                final_x = x + 15
                final_y = y + 10
                if final_x + tooltip_width > screen_width:
                    final_x = x - tooltip_width - 5
                if final_y + tooltip_height > screen_height:
                    final_y = y - tooltip_height - 5
                if final_x < 0: final_x = 0
                if final_y < 0: final_y = 0

                self.tooltip_window.geometry(f"+{final_x}+{final_y}")

            except Exception as e_create:
                logging.error(f"Tooltip oluşturulurken hata: {e_create}", exc_info=True)
                if self.tooltip_window and self.tooltip_window.winfo_exists():
                    try: self.tooltip_window.destroy()
                    except: pass
                self.tooltip_window = None

        async def _fetch_address_and_display_async():
            lat = self.model.current_latitude
            lon = self.model.current_longitude
            full_address = f"{lat:.2f}°, {lon:.2f}° (Adres alınamadı)"
            if lat is not None and lon is not None:
                try:
                    TASK_TIMEOUT = 12
                    fetched_address = await asyncio.wait_for(
                        self.model.run_in_executor(self.model.format_active_location, lat, lon),
                        timeout=TASK_TIMEOUT
                    )
                    full_address = fetched_address 
                    logging.debug(f"Arka planda adres alındı (async/timeout): {full_address}")
                except asyncio.TimeoutError:
                    logging.warning(f"Tooltip için adres alma {TASK_TIMEOUT} saniyede zaman aşımına uğradı.")
                    full_address = f"{lat:.2f}°, {lon:.2f}° (Adres alınamadı - Zaman aşımı)"
                except Exception as e:
                    logging.error(f"Tooltip için adres alınırken hata (async): {e}", exc_info=True)
                    full_address = f"{lat:.2f}°, {lon:.2f}° (Adres alınamadı - Hata)"
            else:
                full_address = "Konum bilgisi yok"

            TkManager.safe_after(0, lambda: _display_tooltip_with_text(full_address, x_root, y_root), timeout=2, context="DisplayTooltipAsync")

        if self.model.async_loop:
            logging.debug("Tooltip için adres getirme görevi asyncio loop'a gönderiliyor...")
            asyncio.run_coroutine_threadsafe(_fetch_address_and_display_async(), self.model.async_loop)
        else:
            logging.error("Async loop çalışmıyor, tooltip adresi alınamıyor.")
            _display_tooltip_with_text("Hata: Adres alınamadı", x_root, y_root)

    def hide_tooltip(self, event: Optional[tk.Event] = None) -> None:
        if self.tooltip_window and self.tooltip_window.winfo_exists():
            self.tooltip_window.destroy()
            self.tooltip_window = None
    def schedule_tooltip(self, event: tk.Event) -> None:
        self.cancel_tooltip() 
        try:
            if self.pencere and self.pencere.winfo_exists():
                self.tooltip_after_id = self.pencere.after(500, lambda ev=event: self.show_full_location_tooltip(ev))
            else:
                logging.warning("schedule_tooltip: Cannot schedule, window does not exist.")
                self.tooltip_after_id = None
        except Exception as e:
            logging.error(f"schedule_tooltip: Error scheduling tooltip: {e}", exc_info=True)
            self.tooltip_after_id = None

    def cancel_tooltip(self, event: Optional[tk.Event] = None) -> None:
        if self.tooltip_after_id:
            try:
                if self.pencere and self.pencere.winfo_exists():
                    self.pencere.after_cancel(self.tooltip_after_id)
                else:
                    logging.warning(f"cancel_tooltip: Cannot cancel after_id {self.tooltip_after_id}, window does not exist.")
            except tk.TclError as e_cancel:
                 logging.debug(f"cancel_tooltip: TclError cancelling after_id {self.tooltip_after_id} (likely already run/cancelled): {e_cancel}")
            except Exception as e:
                logging.error(f"cancel_tooltip: Error cancelling after_id {self.tooltip_after_id}: {e}", exc_info=True)
            finally:
                self.tooltip_after_id = None
        self.hide_tooltip(event)
    @run_on_main_thread
    def guncelle_takvim(self, imsakiye: List[List[str]]) -> None:
        logging.info("guncelle_takvim: imsakiye verisi: %s", imsakiye)
        if hasattr(self, 'imsak_tree') and self.imsak_tree is not None:
            for item in self.imsak_tree.get_children():
                self.imsak_tree.delete(item)
        else:
            self.takvim_frame = ttk.Frame(self.pencere)
            self.takvim_frame.pack(fill="both", expand=True)
            columns = ("Tarih", "İmsak", "Güneş", "Öğle", "İkindi", "Akşam", "Yatsı")
            self.imsak_tree = ttk.Treeview(self.takvim_frame, columns=columns, show="headings", selectmode="extended", height=10)
            for col in columns:
                if col == "Tarih":
                    self.imsak_tree.heading(col, text=col, anchor="w")
                    self.imsak_tree.column(col, anchor="w", width=180, stretch=False, minwidth=180)
                else:
                    self.imsak_tree.heading(col, text=col, anchor="center")
                    self.imsak_tree.column(col, anchor="center", width=90, stretch=True, minwidth=60)
            self.imsak_tree.pack(fill="both", expand=True)
        for row in imsakiye:
            self.imsak_tree.insert("", "end", values=row)
        logging.info("İmsak takvimi güncellendi.")
    def update_countdown(self) -> None:
        if not self.current_ezan_saatleri:
            TkManager.safe_after(100, self.update_countdown, run_in_thread=False, context="UpdateCountdown-StartWait")
            return
        tz_str = self.current_ezan_saatleri.get("timezone")
        tz = get_timezone_from_str(tz_str)
        now = get_utc_now().astimezone(tz)
        try:
            imsak_str = self.current_ezan_saatleri.get("fajr", "06:00")
            iftar_str = self.current_ezan_saatleri.get("maghrib", "20:00")
            imsak_time = datetime.combine(now.date(), datetime.strptime(imsak_str, "%H:%M").time(), tzinfo=tz)
            iftar_time = datetime.combine(now.date(), datetime.strptime(iftar_str, "%H:%M").time(), tzinfo=tz)
        except ValueError as ve:
            self.controller.log_message(f"Zaman formatı hatası: {ve}. Varsayılan saatler kullanılacak.")
            imsak_time = datetime.combine(now.date(), datetime.strptime("06:00", "%H:%M").time(), tzinfo=tz)
            iftar_time = datetime.combine(now.date(), datetime.strptime("20:00", "%H:%M").time(), tzinfo=tz)
        bir_onceki = iftar_time - timedelta(days=1)
        fasting_duration = iftar_time - imsak_time
        fasting_duration_str = f"{int(fasting_duration.total_seconds()//3600):02d}:{int((fasting_duration.total_seconds()%3600)//60):02d}"
        if now < imsak_time:
            kalan = imsak_time - now
            kalan_str = str(kalan).split(".")[0]
            free_duration = imsak_time - bir_onceki
            free_str = f"{int(free_duration.total_seconds()//3600):02d}:{int((free_duration.total_seconds()%3600)//60):02d}"
            toplam = (imsak_time - bir_onceki).total_seconds()
            gecen = (now - bir_onceki).total_seconds()
            yuzde = (gecen / toplam) * 100
            self.sayac_label.config(text=f"Sahura Kalan Süre: {kalan_str}")
            self.yuzde_etiket.config(text=f"Serbest yeme içme süresi: {free_str}, %{yuzde:.4f} tamamlandı")
            self.yuzde_cubugu["value"] = yuzde
        elif now < iftar_time:
            kalan = iftar_time - now
            kalan_str = str(iftar_time - now).split(".")[0]
            toplam = (iftar_time - imsak_time).total_seconds()
            gecen = (now - imsak_time).total_seconds()
            yuzde = (gecen / toplam) * 100
            self.sayac_label.config(text=f"İftara Kalan Süre: {kalan_str}")
            self.yuzde_etiket.config(text=f"Oruç süresi: {fasting_duration_str}, %{yuzde:.4f} tamamlandı")
            self.yuzde_cubugu["value"] = yuzde
        else:
            next_imsak = imsak_time + timedelta(days=1)
            kalan = next_imsak - now
            kalan_str = str(kalan).split(".")[0]
            free_duration = next_imsak - iftar_time
            free_str = f"{int(free_duration.total_seconds()//3600):02d}:{int((free_duration.total_seconds()%3600)//60):02d}"
            toplam = free_duration.total_seconds()
            gecen = (now - imsak_time).total_seconds() - (iftar_time - imsak_time).total_seconds()
            yuzde = (gecen / toplam) * 100
            self.sayac_label.config(text=f"Sahura Kalan Süre: {kalan_str}")
            self.yuzde_etiket.config(text=f"Serbest yeme içme süresi: {free_str}, %{yuzde:.4f} tamamlandı")
            self.yuzde_cubugu["value"] = yuzde
        TkManager.safe_after(1000, self.update_countdown, run_in_thread=False, context="UpdateCountdown-Tick")

    def update_vakit_highlights(self) -> None:
        try:
            if not (self.pencere and self.pencere.winfo_exists()):
                return
            if self.current_ezan_saatleri:
                self.arayuzu_guncelle(self.current_ezan_saatleri)
        except Exception as e:
            logging.error(f"update_vakit_highlights hatası: {e}")
        finally:
            try:
                if self.pencere and self.pencere.winfo_exists():
                    TkManager.safe_after(1000, self.update_vakit_highlights, run_in_thread=False, context="UpdateVakitHighlights-Resched")
            except Exception as e_resched:
                logging.debug(f"update_vakit_highlights yeniden zamanlanamadı: {e_resched}")
    @run_on_main_thread
    def run_iftar_app(self) -> None:
        if TkManager.main_instance is None:
            self.pencere = tk.Tk()
            TkManager.main_instance = self.pencere
            logging.info("Yeni ana Tkinter penceresi oluşturuldu ve TkManager'a atandı.")
        else:
            self.pencere = TkManager.main_instance
            logging.warning("Mevcut ana Tkinter penceresi yeniden kullanılıyor.")
        TkManager.main_instance = self.pencere
        self.pencere.after(50, TkManager.process_callback_queue)
        self.check_module_updates_var = tk.BooleanVar(master=self.pencere)
        current_val = self.model.config_manager.get("check_module_updates", "False")
        self.check_module_updates_var.set(current_val.lower() == "true")
        def tk_report_callback_exception(exc, val, tb):
            error_msg = "".join(traceback.format_exception(exc, val, tb))
            logging.exception("Tkinter hatası: %s", error_msg)
            safe_showerror("Hata", f"Beklenmeyen bir Tkinter hatası oluştu. Lütfen log dosyasını kontrol ediniz.\n\nHata Detayları:\n{error_msg}")
            self.controller.log_message("Tkinter hatası: " + error_msg)
        self.pencere.report_callback_exception = tk_report_callback_exception
        self.pencere.withdraw()
        self.patch_messagebox_functions()
        pencere_boyutu = self.get_window_geometry()
        self.windowed_geometry = pencere_boyutu
        if not self.model.DEVELOPER_MODE:
            width_part, plus_part = pencere_boyutu.split('x', 1)
            width_str = width_part
            new_height = 650
            if '+' in plus_part:
                old_height, offset_part = plus_part.split('+', 1)
                pencere_boyutu = f"{width_str}x{new_height}+{offset_part}"
            else:
                pencere_boyutu = f"{width_str}x{new_height}"
        local_now = get_utc_now().astimezone()
        baslik_text = ("Hoş geldin, Ramazan " + str(local_now.year) + "♥" if self.model.ramazan_mi() else "Namaz Vakitleri")
        self.pencere.title(f"{baslik_text} - İftar Sayacı {APP_VERSION}")
        self.pencere.geometry(pencere_boyutu)
        self.pencere.update_idletasks()
        TkManager.safe_after(100, self.controller.finalize_system_check, context="FinalizeSystemCheck")
        TkManager.safe_after(100, lambda: (self.pencere.bind("<F11>", self.toggle_fullscreen), self.pencere.bind("<Escape>", lambda e: self.pencere.attributes("-fullscreen", False))), context="BindFullscreenKeys")
        self.pencere.minsize(650, 400)
        self.create_fonts(self.pencere)
        self.pencere.bind("<Configure>", self.on_configure)
        menubar = tk.Menu(self.pencere)
        self.pencere.config(menu=menubar)
        top_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Menü", menu=top_menu)
        top_menu.add_command(label="Hakkında", command=self.controller.show_about)
        top_menu.add_checkbutton(label="Açılışta Modül Güncellemelerini Kontrol Et",
                                 variable=self.check_module_updates_var,
                                 command=self.toggle_module_update_check)
        self.developer_mode_var = tk.BooleanVar(master=self.pencere)
        dev_mode_value = self.model.config_manager.get("DEVELOPER_MODE", "False")
        self.developer_mode_var.set(dev_mode_value.lower() == "true")
        top_menu.add_checkbutton(
            label="Geliştirici Modu",
            variable=self.developer_mode_var,
            command=self.toggle_developer_mode
        )
        ust_frame = ttk.Frame(self.pencere)
        ust_frame.pack(side="top", fill="x", padx=10, pady=10)
        ust_frame.columnconfigure(0, weight=0)
        ust_frame.columnconfigure(1, weight=1)
        ust_frame.columnconfigure(2, weight=0)
        default_width_left = 300
        new_width_left = int(default_width_left * 1)
        default_height_left = 115
        ayarlar_frame = ttk.Labelframe(ust_frame, text="Ayarlar", labelanchor="n", padding=10, width=new_width_left, height=default_height_left)
        ayarlar_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        ayarlar_frame.grid_propagate(False)
        ust_frame.columnconfigure(0, minsize=new_width_left)
        ust_frame.rowconfigure(0, minsize=default_height_left)
        btn_otomatik_konum = self.create_logged_button(ayarlar_frame, text="Otomatik Konum Seç", command=self.controller.konum_guncelle)
        btn_otomatik_konum.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        btn_suanki_konum = self.create_logged_button(ayarlar_frame, text="Aktif Konumu Göster", command=self.controller.suanki_konum_goster)
        btn_suanki_konum.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        btn_metod_degistir = self.create_logged_button(ayarlar_frame, text="Yöntem Değiştir", command=self.controller.metod_degistir)
        btn_metod_degistir.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
        ayarlar_frame.columnconfigure(0, weight=1)
        ayarlar_frame.columnconfigure(1, weight=1)
        baslik_frame = ttk.Frame(ust_frame)
        baslik_frame.grid(row=0, column=1, padx=10, sticky="n")
        baslik_label = ttk.Label(baslik_frame, text=baslik_text, font=self.large_bold_font)
        baslik_label.pack()
        default_width = 330
        new_width = int(default_width * 1)
        default_height = 115
        sag_frame = ttk.Labelframe(ust_frame, text="Uygulama Sağlığı", labelanchor="n", padding=5, width=new_width, height=default_height)
        sag_frame.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)
        sag_frame.grid_propagate(False)
        ust_frame.columnconfigure(2, minsize=new_width)
        center_container = ttk.Frame(sag_frame)
        center_container.grid(row=0, column=0, sticky="w")
        domain, ping_ms = self.model.api_canlılık_durumu()
        api_emoji = "✅" if isinstance(ping_ms, int) and ping_ms < 500 else "❌"
        api_status_text = f"{api_emoji} API Durumu ({domain}): {ping_ms} ms"
        api_status_label = ttk.Label(center_container, text=api_status_text, font=self.default_font, anchor="w", justify="left")
        api_status_label.grid(row=0, column=0, sticky="w", padx=6, pady=2)
        system_frame = ttk.Frame(center_container)
        system_frame.grid(row=1, column=0, sticky="w", padx=5, pady=2)
        sys_icon, sys_msg = self.model.sistem_saati_kontrol_alternative()
        self.sistem_saati_label = ttk.Label(system_frame, text=f"{sys_icon} Sistem Saati Kontrolü", font=self.default_font, anchor="w", justify="left")
        self.sistem_saati_label.grid(row=0, column=0, sticky="w")
        compare_button = self.create_logged_button(system_frame, text="🔄 Karşılaştır", command=lambda: (self.controller.log_message("Karşılaştır butonuna basıldı."), TkManager.safe_after(0, self.controller.finalize_system_check)))
        compare_button.grid(row=0, column=1, sticky="w", padx=(5, 0))
        aktif_konum_frame = ttk.Frame(center_container)
        aktif_konum_frame.grid(row=2, column=0, sticky="w", padx=5, pady=2)
        self.aktif_konum_frame = aktif_konum_frame
        static_label = ttk.Label(aktif_konum_frame, text=self.static_prefix if self.model.current_location else "❌ Konum alınamadı.", font=self.default_font, anchor="w", justify="left")
        static_label.grid(row=0, column=0, sticky="w")
        self.dynamic_entry = tk.Entry(aktif_konum_frame, width=29, font=self.default_font, bd=0, relief="flat", exportselection=1)
        self.dynamic_entry.grid(row=0, column=1, sticky="w", padx=(2,0))
        self.dynamic_entry.bind("<Enter>", self.schedule_tooltip)
        self.dynamic_entry.bind("<Leave>", self.cancel_tooltip)
        self.dynamic_entry.bind("<ButtonRelease-1>", self.store_selection)
        self.dynamic_entry.bind("<Button-3>", lambda event: (self.show_text_context_menu(event), "break"))
        self.dynamic_entry.bind("<Control-c>", lambda event: self.copy_text_from_widget(self.dynamic_entry))
        self.Aktif_Konum_Labeli_uygulama_sagligi_icinde_widget_V2()
        self.vakit_cerceve = ttk.Frame(self.pencere)
        self.vakit_cerceve.pack(pady=10, padx=10, fill="x", expand=True)
        if self.model.current_latitude is None or self.model.current_longitude is None:
            enlem, boylam = self.model.DEFAULT_LATITUDE, self.model.DEFAULT_LONGITUDE
        else:
            enlem, boylam = self.model.current_latitude, self.model.current_longitude
        ezan_saatleri = self.model.ezan_saatlerini_hesapla(enlem, boylam, self.model.current_method)
        self.current_ezan_saatleri = ezan_saatleri
        self.arayuzu_guncelle(ezan_saatleri)
        TkManager.safe_after(1000, self.update_vakit_highlights, run_in_thread=False, context="UpdateVakitHighlights-Start")
        iftar_sayaci_cerceve = ttk.Frame(self.pencere)
        iftar_sayaci_cerceve.pack(pady=10, padx=10, fill="x")
        iftar_sayaci_cerceve.columnconfigure(0, weight=1)
        self.sayac_label = ttk.Label(iftar_sayaci_cerceve, text="Sahura Kalan Süre: 00:00:00", font=self.large_bold_font, anchor="center", justify="center")
        self.sayac_label.grid(row=0, column=0, padx=2, pady=5, sticky="ew")
        self.yuzde_cubugu = ttk.Progressbar(iftar_sayaci_cerceve, orient="horizontal", mode="determinate")
        self.yuzde_cubugu.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
        self.yuzde_etiket = ttk.Label(iftar_sayaci_cerceve, text="", font=self.default_font)
        self.yuzde_etiket.grid(row=2, column=0, padx=5, pady=5)
        self.update_countdown()
        imsak_frame = ttk.Frame(self.pencere)
        imsak_frame.pack(fill="x", padx=10, pady=(0, 10))
        hicri_text = self.model.hicri_tarih_header()
        hicri_text_clean = self.model.clean_text(hicri_text)
        clean_text = hicri_text_clean.strip()
        fixed_width = len(clean_text)
        text_pixel_width = self.large_bold_font.measure(clean_text)
        avg_char_width = self.large_bold_font.measure("0")
        entry_width = int(text_pixel_width / avg_char_width) + 1
        imsak_takvimi_baslik = tk.Entry(imsak_frame, font=self.large_bold_font, bd=0, relief="flat", bg=self.pencere.cget("bg"), justify="center", width=entry_width)
        imsak_takvimi_baslik.pack(pady=0)
        imsak_takvimi_baslik.insert(0, clean_text)
        imsak_takvimi_baslik.config(state="readonly")
        def copy_label_text(event: tk.Event) -> None:
            text = event.widget.cget("text")
            self.pencere.clipboard_clear()
            self.pencere.clipboard_append(text)
            print("Kopyalandı:", text)
        def show_context_menu(event: tk.Event) -> None:
            widget = event.widget
            menu = tk.Menu(self.pencere, tearoff=0)
            try:
                _ = widget.selection_get()
                menu.add_command(label="Kopyala", command=lambda: copy_selection(widget))
            except tk.TclError:
                menu.add_command(label="Kopyala", state="disabled")
            menu.tk_popup(event.x_root, event.y_root)
        def copy_selection(widget: tk.Widget) -> None:
            current_instance_id = id(widget)
            current_widget_type = type(widget).__name__
            log_prefix = f"[Patcher V2][Widget ID: {current_instance_id}, Type: {current_widget_type}]"
            logging.debug(f"{log_prefix} local copy_selection başlatıldı.")
            text_to_copy = ""
            try:
                text_to_copy = widget.selection_get()
                logging.debug(f"{log_prefix} copy_selection: Selection found: '{text_to_copy}'")
            except tk.TclError:
                logging.warning(f"{log_prefix} copy_selection: selection_get() failed (No selection).")
                text_to_copy = ""
            except Exception as e:
                logging.error(f"{log_prefix} copy_selection: Error getting selection: {e}", exc_info=True)
                text_to_copy = ""
            if text_to_copy:
                try:
                    logging.info(f"{log_prefix} copy_selection: Attempting to copy: '{text_to_copy}'")
                    widget.clipboard_clear()
                    widget.clipboard_append(text_to_copy)
                    logging.info(f"{log_prefix} copy_selection: Kopyalandı: {text_to_copy}")
                    try:
                        clipboard_after = widget.clipboard_get()
                        if clipboard_after == text_to_copy:
                            logging.info(f"{log_prefix} copy_selection: Clipboard verification PASSED.")
                        else:
                            logging.error(f"{log_prefix} copy_selection: !! Clipboard verification FAILED !! Expected: '{text_to_copy}', Got: '{clipboard_after}'")
                    except Exception as e_verify:
                        logging.warning(f"{log_prefix} copy_selection: Clipboard verification check failed: {e_verify}")
                except Exception as e_clip:
                     logging.error(f"{log_prefix} copy_selection: Clipboard operation failed: {e_clip}", exc_info=True)
                     print(f"HATA: Panoya kopyalarken hata oluştu: {e_clip}")
            else:
                 logging.warning(f"{log_prefix} copy_selection: No text selected to copy (selection failed/empty or Label empty/error).")

        imsak_takvimi_baslik.bind("<Button-3>", show_context_menu)
        imsak_takvimi_baslik.bind("<Control-c>", lambda event: copy_selection(imsak_takvimi_baslik))
        tablo_cerceve = ttk.Frame(self.pencere)
        tablo_cerceve.pack(pady=10, padx=10, fill="both", expand=True)
        icerik_frame = ttk.Frame(tablo_cerceve)
        icerik_frame.pack(fill="both", expand=True)
        columns = ("Tarih", "İmsak", "Güneş", "Öğle", "İkindi", "Akşam", "Yatsı")
        tree = ttk.Treeview(icerik_frame, columns=columns, show="headings", selectmode="extended", height=10)
        for col in columns:
            if col == "Tarih":
                tree.heading(col, text=col, anchor="w")
                tree.column(col, anchor="w", width=180, stretch=False, minwidth=180) 
            else:
                tree.heading(col, text=col, anchor="center")
                tree.column(col, anchor="center", width=90, stretch=True, minwidth=60) 
        scrollbar = ttk.Scrollbar(icerik_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        imsakiye = self.model.imsakiye_takvimini_al()
        for row in imsakiye:
            tree.insert("", "end", values=row)
        context_menu = tk.Menu(self.pencere, tearoff=0)
        context_menu.add_command(label="Kopyala", command=lambda: self.copy_treeview_selection(tree))
        def show_context_menu_tree(event: tk.Event) -> None:
            iid = tree.identify_row(event.y)
            if iid:
                tree.selection_set(iid)
                context_menu.tk_popup(event.x_root, event.y_root)
            context_menu.grab_release()
        tree.bind("<Button-3>", show_context_menu_tree)
        tree.bind("<Control-c>", lambda event: self.copy_treeview_selection(tree))
        tree.bind("<Button-1>", lambda e: "break" if tree.identify_region(e.x, e.y) == "separator" else None)
        def update_tree_columns():
            new_width = int(tree.winfo_width() / len(columns))
            for col in columns:
                tree.column(col, width=new_width)
        def on_resize(event: tk.Event) -> None:
            if hasattr(tree, '_resize_job'):
                tree.after_cancel(tree._resize_job)
            tree._resize_job = tree.after(150, update_tree_columns)
        console_frame = ttk.Frame(self.pencere)
        if self.model.DEVELOPER_MODE:
            console_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        header_frame = ttk.Frame(console_frame)
        header_frame.pack(side="top", fill="x", padx=0, pady=2)
        log_header = ttk.Label(header_frame, text="Konsol Paneli", font=self.bold_font, anchor="w")
        log_header.pack(side="left", padx=(5, 5))
        style = ttk.Style() # Stil objesine erişim (genellikle zaten var olur)
        if not hasattr(self, "_custom_tbutton_style_done"):
            style.configure("Custom.TButton", font=("Segoe UI Emoji", 8))
            self._custom_tbutton_style_done = True
        clear_button = ttk.Button(header_frame, text="Temizle", command=self.controller.clear_log, style="Custom.TButton")
        clear_button.pack(side="right", padx=(5, 8), pady=1)
        console_subframe = ttk.Frame(console_frame)
        console_subframe.pack(side="top", fill="x", expand=False, padx=0, pady=0)
        console_scrollbar = ttk.Scrollbar(console_subframe, orient="vertical")
        console_scrollbar.pack(side="right", fill="y")
        self.ConsolePanel = tk.Text(console_subframe, font=("Courier", 10),
                                    background="black", foreground="green",
                                    insertbackground="green", wrap="word",
                                    state="disabled", yscrollcommand=console_scrollbar.set,
                                    height=8)
        self.ConsolePanel.pack(side="left", fill="x", expand=True)
        console_scrollbar.config(command=self.ConsolePanel.yview)
        self.ConsolePanel.tag_configure("ERROR", foreground="red")
        self.ConsolePanel.tag_configure("WARNING", foreground="orange")
        self.ConsolePanel.tag_configure("INFO", foreground="#00A000")
        self.ConsolePanel.tag_configure("DEBUG", foreground="cyan")
        self.ConsolePanel.tag_configure("DEFAULT", foreground="green")
        self.ConsolePanel.bind("<Button-3>", self.log_text_context_menu)
        self.ConsolePanel.bind("<Control-a>", lambda event: (self.ConsolePanel.tag_add("sel", "1.0", "end"), "break"))
        def on_console_key(e: tk.Event) -> str:
            if e.keysym == 'F4' and (e.state & 0x8): 
                on_closing()
                return "break" 
            elif (e.state & 0x4) and e.keysym.lower() == "c": 
                self.copy_text_from_widget(self.ConsolePanel)
                return "break"
            return None 
        self.ConsolePanel.bind("<Key>", on_console_key)
        cmd_frame = ttk.Frame(console_frame)
        cmd_frame.pack(side="bottom", fill="x", padx=0, pady=0)
        prompt_label = ttk.Label(cmd_frame, text=">", font=("Courier", 10))
        prompt_label.grid(row=0, column=0, padx=(5, 0), pady=2)
        def execute_command_entry(event: tk.Event = None) -> str:
            cmd = command_entry.get().strip()
            if cmd.lower() == "cls":
                self.controller.clear_log()
                command_entry.delete(0, tk.END)
                return "break"
            if len(cmd) > 100:
                self.show_error("Hata", "Komut çok uzun; lütfen 100 karakteri geçmeyen bir komut giriniz.")
                return "break"
            if not self.model.DEVELOPER_MODE:
                self.show_error("Hata", "Komut satırı yalnızca geliştirici modunda aktiftir.")
                return "break"
            self.controller.log_message(f">>> {cmd}")
            command_entry.delete(0, tk.END)
            try:
                result = safe_eval(cmd)
                self.controller.log_message(f"[Komut başarıyla çalıştırıldı.] Sonuç: {result}")
            except Exception as ex:
                logging.exception("Komut çalıştırma sırasında sorun: %s", ex)
                self.controller.log_message(f"Hata: {ex}.")
            return "break"
        command_entry = ttk.Entry(cmd_frame, font=("Courier", 10))
        command_entry.grid(row=0, column=1, padx=(2, 5), pady=2, sticky="ew")
        cmd_frame.columnconfigure(1, weight=1)
        command_entry.bind("<Return>", execute_command_entry)
        command_entry.bind("<Control-a>", lambda event: (command_entry.select_range(0, tk.END),
                                                         command_entry.icursor(tk.END), "break"))
        def pencere_kapat() -> None:
            try:
                try:
                    if not (self.pencere and self.pencere.winfo_exists()):
                        return
                except Exception:
                    return
                if self.pencere.attributes("-fullscreen"):
                    self.pencere.attributes("-fullscreen", False)
                    self.pencere.update_idletasks()
                current_geom = self.windowed_geometry if self.windowed_geometry else self.pencere.winfo_geometry()
                logging.info("Kapanışta alınan pencere geometrisi: %s", current_geom)
                try:
                    width_str, rest = current_geom.split("x")
                    height_str, pos_str = rest.split("+", 1)
                    width = int(width_str)
                    height = int(height_str)
                    x_offset, y_offset = map(int, pos_str.split("+"))
                except Exception as parse_err:
                    logging.error("Geometri ayrıştırma hatası: %s", parse_err)
                    width, height, x_offset, y_offset = 965, 850, 480, 110
                desired_height = 850
                if height < desired_height:
                    fark = desired_height - height
                    logging.info("Kapanışta height değeri %d piksel düşük; düzeltme uygulanıyor.", fark)
                    height = desired_height
                adjusted_geom = f"{width}x{height}+{x_offset}+{y_offset}"
                logging.info("Kaydedilecek pencere geometrisi: %s", adjusted_geom)
                self.model.config_manager.set("pencere_boyutu", adjusted_geom)
                self.model.config_manager.set("konum", self.model.current_location)
                self.model.config_manager.set("metod", self.model.current_method)
                self.model.config_manager.set("check_module_updates", "True" if CHECK_MODULE_UPDATES else "False")
                self.model.config_manager.set("DEVELOPER_MODE", "True" if self.model.DEVELOPER_MODE else "False")
                self.model.config_manager.save()
                try:
                    after_ids = self.pencere.tk.call('after', 'info')
                    if after_ids:
                        if isinstance(after_ids, tuple):
                            for after_id in after_ids:
                                try:
                                    self.pencere.after_cancel(after_id)
                                except Exception as e:
                                    logging.error("after_cancel sırasında hata (ID: %s): %s", after_id, e)
                        else:
                            for after_id in after_ids.split():
                                try:
                                    self.pencere.after_cancel(after_id)
                                except Exception as e:
                                    logging.error("after_cancel sırasında hata (ID: %s): %s", after_id, e)
                except Exception as e:
                    logging.error("after callback iptali sırasında hata: %s", e)
            except Exception as e:
                logging.error("Pencere kapanışında hata oluştu: %s", e)
            finally:
                try:
                    self.model.executor.shutdown(wait=False)
                    self.model.GLOBAL_SESSION.close()
                    if self.pencere and self.pencere.winfo_exists():
                        self.pencere.destroy()
                        logging.info(f"{datetime.now()} - Tkinter penceresi kapatıldı.")
                except Exception as e:
                    logging.error(f"{datetime.now()} - Tkinter penceresi kapatılırken hata oluştu: {e}")
                graceful_shutdown()
        def on_closing():
            if safe_askyesno("Çıkış", "Uygulamadan çıkmak istediğinize emin misiniz?"):
                pencere_kapat()
        self.pencere.protocol("WM_DELETE_WINDOW", on_closing)
        self.pencere.bind("<Alt-F4>", lambda event: on_closing())
        TkManager.safe_after(100, lambda: (self.pencere.bind("<F11>", self.toggle_fullscreen), self.pencere.bind("<Escape>", lambda e: self.pencere.attributes("-fullscreen", False))), context="BindFullscreenKeys")
        def periodic_console_update(update_context: str = "PeriodicConsoleUpdate") -> None:
            try:
                if self.pencere and self.pencere.winfo_exists():
                    self.update_console_from_model()
                else:
                    logging.info(f"Konsol güncelleme durduruldu ({update_context}) (Pencere kapatılmış).")
                    return 
            except Exception as e:
                logging.error(f"{update_context} hatası: {e}")
            if self.pencere and self.pencere.winfo_exists():
                TkManager.safe_after(500, periodic_console_update, run_in_thread=False, context=update_context)
            else:
                 logging.debug("Periodic console update rescheduling stopped as window no longer exists.")
        TkManager.safe_after(500, periodic_console_update, run_in_thread=False, context="InitialConsoleUpdate")
        self.pencere.deiconify()
        self.pencere.mainloop()
    @run_on_main_thread
    def cleanup(self) -> None:
        try:
            self.model.executor.shutdown(wait=True)
            self.model.GLOBAL_SESSION.close()
            if self.pencere:
                self.pencere.destroy()
        except Exception as e:
            logging.error(f"Temizleme sırasında sorun: {e}")
    @run_on_main_thread
    def on_configure(self, event: tk.Event) -> None:
        current_time = time.time()
        if current_time - self._last_configure_time < 0.3:
            return
        self._last_configure_time = current_time
        try:
            if not self.pencere.attributes("-fullscreen"):
                self.windowed_geometry = self.pencere.geometry()
        except Exception as e:
            logging.exception("Pencere konfigürasyonu sırasında sorun: %s", e)
    def patch_messagebox_functions(self) -> None:
        def _limited_messagebox_wrapper(original_function: Callable, max_length: int = 1024) -> Callable:
            def wrapper(title: Optional[str] = None, message: Optional[str] = None, *args: Any, **kwargs: Any):
                if threading.current_thread() is not threading.main_thread():
                    logging.error("GUI messagebox fonksiyonu %s ana iş parçacığı dışında çağrıldı.", original_function.__name__)
                    return None
                if message is not None and len(message) > max_length:
                    message = message[:max_length] + "..."
                return original_function(title, message, *args, **kwargs)
            return wrapper
        functions = ["showinfo", "showwarning", "askquestion", "askokcancel", "askyesno", "askretrycancel"]
        for func_name in functions:
            original_func = getattr(messagebox, func_name)
            limited_func = _limited_messagebox_wrapper(original_func, max_length=1024)
            setattr(messagebox, func_name, limited_func)
        _original_showerror = messagebox.showerror
        def limited_showerror(title: str, message: str, *args: Any, **kwargs: Any):
            if threading.current_thread() is not threading.main_thread():
                logging.error("GUI messagebox.showerror ana iş parçacığı dışında çağrıldı.")
                return None
            MAX_LENGTH = 1024
            if len(message) > MAX_LENGTH:
                message = message[:MAX_LENGTH] + "..."
            return _original_showerror(title, message, *args, **kwargs)
        messagebox.showerror = limited_showerror
    def get_window_geometry(self) -> str:
        saved_geom = self.model.config_manager.get("pencere_boyutu", "")
        if saved_geom and GEOMETRY_RE.match(saved_geom):
            return saved_geom
        width = 965
        if not self.model.DEVELOPER_MODE:
            height = 650
        else:
            height = 860
        sw = self.pencere.winfo_screenwidth()
        sh = self.pencere.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        return f"{width}x{height}+{x}+{y}"
    def create_fonts(self, root: tk.Tk) -> None:
        self.default_font = tkFont.Font(root, family="Segoe UI Emoji", size=10)
        self.bold_font = tkFont.Font(root, family="Segoe UI Emoji", size=10, weight="bold")
        self.large_bold_font = tkFont.Font(root, family="Segoe UI Emoji", size=14, weight="bold")
        self.button_font = tkFont.Font(root, family="Segoe UI Emoji", size=10)
    @run_on_main_thread
    def arayuzu_guncelle(self, ezan_saatleri: Dict[str, str]) -> None:
        if self.prayer_labels is None or self.prayer_time_labels is None:
            self.prayer_labels = []
            self.prayer_time_labels = []
            for i in range(6):
                lbl = ttk.Label(self.vakit_cerceve, text="", font=self.default_font, anchor="center", justify="center")
                lbl.grid(row=0, column=i, padx=2, pady=5, sticky="nsew")
                self.prayer_labels.append(lbl)
                lbl2 = ttk.Label(self.vakit_cerceve, text="", font=self.default_font, anchor="center", justify="center")
                lbl2.grid(row=1, column=i, padx=2, pady=5, sticky="nsew")
                self.prayer_time_labels.append(lbl2)
            for i in range(6):
                self.vakit_cerceve.columnconfigure(i, weight=1)
        vakitler = getattr(self, "_vakitler", None)
        if vakitler is None:
            vakitler = ("İmsak", "Güneş", "Öğle", "İkindi", "Akşam", "Yatsı")
            self._vakitler = vakitler
        vakitler_ingilizce = getattr(self, "_vakitler_ing", None)
        if vakitler_ingilizce is None:
            vakitler_ingilizce = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")
            self._vakitler_ing = vakitler_ingilizce
        saatler = tuple(ezan_saatleri.get(v, "N/A") for v in vakitler_ingilizce)
        tz_str = ezan_saatleri.get("timezone")
        cached_tz_str = getattr(self, "_cached_tz_str", None)
        cached_tz = getattr(self, "_cached_tz", None)
        if cached_tz is None or cached_tz_str != tz_str:
            tz = get_timezone_from_str(tz_str)
            self._cached_tz = tz
            self._cached_tz_str = tz_str
        else:
            tz = cached_tz
        now = get_utc_now().astimezone(tz)
        now_date = now.date()
        if not hasattr(self, "_time_parse_cache"):
            self._time_parse_cache = {}
        time_cache = self._time_parse_cache
        current_tp_key = (now_date, tz_str, saatler)
        last_tp_key = getattr(self, "_tp_key", None)
        last_tp_values = getattr(self, "_tp_values", None)
        if last_tp_key == current_tp_key and last_tp_values is not None:
            today_prayers = list(last_tp_values)
        else:
            today_prayers = []
            append_tp = today_prayers.append
            for i, time_str in enumerate(saatler):
                prayer_time = None
                try:
                    t = time_cache.get(time_str)
                    if t is None:
                        hh = int(time_str[:2]); mm = int(time_str[3:5])
                        t = datetime(1900, 1, 1, hh, mm).time()
                        time_cache[time_str] = t
                    prayer_time = datetime.combine(now_date, t, tzinfo=tz)
                except Exception as e:
                    logging.exception("Zaman dönüştürmede hata (%s): %s", vakitler[i], e)
                    prayer_time = None
                append_tp(prayer_time)
            self._tp_key = current_tp_key
            self._tp_values = tuple(today_prayers)
        current_index = -1
        next_index = -1
        if today_prayers[0] is not None and now < today_prayers[0]:
            yesterday = now_date - timedelta(days=1)
            try:
                last_ts = saatler[-1]
                t_last = time_cache.get(last_ts)
                if t_last is None:
                    hh = int(last_ts[:2]); mm = int(last_ts[3:5])
                    t_last = datetime(1900, 1, 1, hh, mm).time()
                    time_cache[last_ts] = t_last
                yesterday_yatsi = datetime.combine(yesterday, t_last, tzinfo=tz)
            except Exception as e:
                logging.exception("Dünün yatsı vaktinin hesaplanmasında hata: %s", e)
                yesterday_yatsi = None
            if yesterday_yatsi is not None:
                current_index = 5
                next_index = 0
            else:
                current_index = 0
        elif today_prayers[-1] is not None and now > today_prayers[-1]:
            current_index = len(today_prayers) - 1
            next_index = 0
        else:
            for i, prayer_time in enumerate(today_prayers):
                if prayer_time is None:
                    continue
                if prayer_time <= now:
                    current_index = i
                elif prayer_time > now and next_index == -1:
                    next_index = i
        pair = (current_index, next_index)
        if self._last_vakit_indices != pair:
            logging.info("Mevcut vakit indeksi: %s, Sonraki vakit indeksi: %s", current_index, next_index)
            self._last_vakit_indices = pair
        if not hasattr(self, "_pl_state"):
            self._pl_state = [None] * 6
            self._pl_time_state = [None] * 6
        labels = self.prayer_labels
        time_labels = self.prayer_time_labels
        default_font = self.default_font
        bold_font = self.bold_font
        emojis = self.model.emojiler
        pl_state = self._pl_state
        pl_time_state = self._pl_time_state
        label_texts = getattr(self, "_label_texts", None)
        emoji_snapshot = getattr(self, "_emoji_snapshot", None)
        current_emoji_tuple = tuple(emojis)
        if getattr(self, "_last_saatler", None) == saatler and self._last_vakit_indices == pair and emoji_snapshot == current_emoji_tuple:
            return
        if label_texts is None or emoji_snapshot != current_emoji_tuple:
            label_texts = tuple(f"{vakitler[i]} ({vakitler_ingilizce[i]}) {emojis[i]}" for i in range(6))
            self._label_texts = label_texts
            self._emoji_snapshot = current_emoji_tuple
        for i in range(6):
            text_str = label_texts[i]
            if i == next_index:
                fg_color = "red"
                font_to_use = default_font
            elif i == current_index:
                fg_color = "green"
                font_to_use = bold_font
            else:
                fg_color = "black"
                font_to_use = default_font
            new_label_state = (text_str, font_to_use, fg_color)
            if pl_state[i] != new_label_state:
                labels[i].config(text=text_str, font=font_to_use, foreground=fg_color)
                pl_state[i] = new_label_state
            new_time_state = (saatler[i], font_to_use, fg_color)
            if pl_time_state[i] != new_time_state:
                time_labels[i].config(text=saatler[i], font=font_to_use, foreground=fg_color)
                pl_time_state[i] = new_time_state
        self._last_saatler = saatler
        
    @run_on_main_thread
    def show_info(self, msg: str) -> None:
        safe_showinfo("Bilgi", msg)
    @run_on_main_thread
    def show_error(self, title: str, msg: str) -> None:
        safe_showerror(title, msg)
    def ask_string(self, title: str, prompt: str) -> Optional[str]:
        input_str = safe_askstring(title, prompt)
        if input_str is not None:
            MAX_LEN = 3
            if len(input_str) > MAX_LEN:
                logging.warning("Kullanıcı girdisi %d karakteri aştı, ilk %d karakter alınıyor.", len(input_str), MAX_LEN)
                return input_str[:MAX_LEN].strip()
            else:
                 return input_str.strip()
        return None
    @run_on_main_thread
    def update_console_from_model(self, max_lines: int = 1000) -> None:
        try:
            if not (self.ConsolePanel and self.ConsolePanel.winfo_exists()):
                return
        except Exception as e_check:
            logging.error("Konsol durumu kontrol edilirken hata: %s", e_check)
            return

        new_messages = []
        log_read_limit = 500
        read_count = 0
        while not self.model.log_buffer.empty() and read_count < log_read_limit:
            try:
                msg = self.model.log_buffer.get_nowait()
                new_messages.append(msg)
                read_count += 1
            except queue.Empty:
                break
            except Exception as e_get:
                logging.error("Log kuyruğundan okuma hatası: %s", e_get)
                break

        if new_messages:
            try:
                self.ConsolePanel.configure(state="normal")

                current_line_count_str = self.ConsolePanel.index("end-1c").split('.')[0]
                try:
                    current_line_count = int(current_line_count_str)
                except ValueError:
                    current_line_count = 0

                lines_to_be_added = sum(msg.count('\n') for msg in new_messages)

                if current_line_count + lines_to_be_added > max_lines:
                    lines_to_delete = (current_line_count + lines_to_be_added) - max_lines
                    delete_end_index = f"{lines_to_delete + 1}.0"
                    self.ConsolePanel.delete("1.0", delete_end_index)

                for msg in new_messages:
                    tag_to_apply = "DEFAULT"
                    level_match = LOG_LEVEL_RE.search(msg)

                    if level_match:
                        level_name = level_match.group(1) or level_match.group(2)
                        if level_name == "ERROR": tag_to_apply = "ERROR"
                        elif level_name == "WARNING": tag_to_apply = "WARNING"
                        elif level_name == "INFO": tag_to_apply = "INFO"
                        elif level_name == "DEBUG": tag_to_apply = "DEBUG"
                    elif msg.startswith("HATA:") or " - ERROR - " in msg:
                        tag_to_apply = "ERROR"
                    elif " - WARNING - " in msg:
                        tag_to_apply = "WARNING"

                    self.ConsolePanel.insert("end", msg, (tag_to_apply,))

                self.ConsolePanel.see("end")

            except tk.TclError as e_tcl:
                logging.error("Konsol güncellenirken TclError: %s", e_tcl)
            except Exception as e_main:
                logging.exception("Konsol güncellenirken beklenmeyen hata: %s", e_main)
            finally:
                try:
                    if self.ConsolePanel and self.ConsolePanel.winfo_exists():
                        self.ConsolePanel.configure(state="disabled")
                except Exception as e_final:
                    logging.error("Konsol state'i 'disabled' yapılırken hata: %s", e_final)

    @run_on_main_thread
    def clear_console_panel(self) -> None:
        if self.ConsolePanel:
            try:
                self.ConsolePanel.configure(state="normal")
                self.ConsolePanel.delete("1.0", "end")
                self.ConsolePanel.update_idletasks()
                self.ConsolePanel.configure(state="disabled")
            except Exception as e:
                logging.exception("ConsolePanel temizlenirken sorun: %s", e)
    def create_logged_button(self, master: tk.Widget, **kwargs: Any) -> ttk.Button:
        cmd = kwargs.get("command")
        text_for_log = kwargs.get("text", "Buton")
        def new_callback(*args: Any, **kw: Any) -> Any:
            self.controller.log_message(f"Butona tıklandı: {text_for_log}")
            if cmd:
                return cmd(*args, **kw)
        kwargs["command"] = new_callback
        kwargs.pop("font", None)
        style_name = "Custom.TButton"
        if not hasattr(self, "_custom_tbutton_style_done"):
            ttk.Style().configure(style_name, font=("Segoe UI Emoji", 8))
            self._custom_tbutton_style_done = True
        kwargs["style"] = style_name
        return ttk.Button(master, **kwargs)
    @staticmethod
    def on_text_click(event: tk.Event) -> None:
        try:
            if event.widget.tag_ranges("sel"):
                event.widget.tag_remove("sel", "1.0", "end")
        except tk.TclError:
            pass
    def copy_treeview_selection(self, tree_widget: ttk.Treeview) -> None:
        instance_id = id(tree_widget)
        log_prefix = f"[Patcher V2][Widget ID: {instance_id}, Type: Treeview]"
        logging.debug(f"{log_prefix} copy_treeview_selection başlatıldı.")
        selected_items = tree_widget.selection()
        if selected_items:
            lines = []
            for item in selected_items:
                try:
                    row_values = tree_widget.item(item, "values")
                    lines.append("\t".join(map(str, row_values)))
                except Exception as e_item:
                    logging.error(f"{log_prefix} Error getting item '{item}' values: {e_item}")
            final_text_to_copy = "\n".join(lines)
            if final_text_to_copy:
                try:
                    logging.info(f"{log_prefix} Attempting to copy to clipboard: '{final_text_to_copy}'")
                    tree_widget.master.clipboard_clear()
                    tree_widget.master.clipboard_append(final_text_to_copy)
                    logging.info(f"{log_prefix} Kopyalandı: {final_text_to_copy}")
                    try:
                        clipboard_after = tree_widget.master.clipboard_get()
                        if clipboard_after == final_text_to_copy:
                            logging.info(f"{log_prefix} Clipboard verification PASSED.")
                        else:
                            logging.error(f"{log_prefix} !! Clipboard verification FAILED !! Expected: '{final_text_to_copy}', Got: '{clipboard_after}'")
                    except Exception as e_verify:
                        logging.warning(f"{log_prefix} Clipboard verification check failed: {e_verify}")

                except Exception as e_clip:
                    logging.error(f"{log_prefix} Clipboard operation failed: {e_clip}", exc_info=True)
                    safe_showerror("Kopyalama Hatası", f"Treeview verisi panoya kopyalanamadı:\n{e_clip}")
            else:
                logging.warning(f"{log_prefix} No valid text generated from selected Treeview items.")
        else:
            logging.warning(f"{log_prefix} No items selected in Treeview.")

    def log_text_context_menu(self, event: tk.Event) -> None:
        menu = tk.Menu(self.ConsolePanel, tearoff=0)
        menu.add_command(label="Kopyala", command=lambda: self.copy_text_from_widget(self.ConsolePanel))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()
    @run_on_main_thread
    def update_sistem_saati_label(self, icon: str, msg: str) -> None:
        if self.sistem_saati_label:
            self.sistem_saati_label.config(text=f"{icon} Sistem Saati Kontrolü: {msg}")

def graceful_shutdown():
    SHUTDOWN_JOIN_TIMEOUT = 5
    resources_closed = True

    try:
        if model.executor:
            model.executor.shutdown(wait=False)
            logging.info(f"{datetime.now()} - Thread havuzu kapatma isteği gönderildi.")
            start_time = time.time()
            while not model.executor._shutdown and time.time() - start_time < SHUTDOWN_JOIN_TIMEOUT:
                time.sleep(0.1)
            if not model.executor._shutdown:
                logging.error("Thread havuzu kapanmadı, zorla sonlandırılıyor.")
                resources_closed = False
            else:
                logging.info(f"{datetime.now()} - Thread havuzu başarıyla kapatıldı.")
    except Exception as e:
        logging.error(f"{datetime.now()} - Thread havuzu kapanırken hata oluştu: {e}")
        resources_closed = False
    try:
        if model.GLOBAL_SESSION:
            model.GLOBAL_SESSION.close()
            logging.info(f"{datetime.now()} - HTTP oturumu başarıyla kapatıldı.")
    except Exception as e:
        logging.error(f"{datetime.now()} - HTTP oturumu kapatılırken hata oluştu: {e}")
        resources_closed = False
    try:
        if view.pencere is not None:
            try:
                exists = view.pencere.winfo_exists()
            except Exception:
                exists = False
            if exists:
                view.pencere.destroy()
                logging.info(f"{datetime.now()} - Tkinter penceresi kapatıldı.")
    except Exception as e:
        logging.error(f"{datetime.now()} - Tkinter penceresi kapatılırken hata oluştu: {e}")
        resources_closed = False
    try:
        if hasattr(model, 'log_queue_listener') and model.log_queue_listener:
            model.log_queue_listener.stop()
            logging.info(f"{datetime.now()} - Günlük dinleyicisi başarıyla kapatıldı.")
            if hasattr(model.log_queue_listener, 'join'):
                model.log_queue_listener.join(timeout=SHUTDOWN_JOIN_TIMEOUT)
                if getattr(model.log_queue_listener, 'is_alive', lambda: False)():
                    logging.warning(f"{datetime.now()} - Log queue listener hala aktif, ikinci join denemesi yapılıyor.")
                    model.log_queue_listener.join(timeout=SHUTDOWN_JOIN_TIMEOUT)
                    if getattr(model.log_queue_listener, 'is_alive', lambda: False)():
                        logging.error(f"{datetime.now()} - Log queue listener zorla sonlandırılamadı.")
                        resources_closed = False
                logging.info(f"{datetime.now()} - Günlük dinleyici thread'i sonlandı.")
    except Exception as e:
        logging.error(f"{datetime.now()} - Günlük dinleyicisi kapatılırken hata oluştu: {e}")
        resources_closed = False
    for handler in logging.getLogger().handlers:
        if isinstance(handler, LogBufferHandler):
            try:
                handler.flush()
                handler.close()
                logging.info(f"{datetime.now()} - LogBufferHandler temizlendi ve kapatıldı.")
            except Exception as e:
                logging.error(f"{datetime.now()} - LogBufferHandler temizlenirken hata oluştu: {e}")
                resources_closed = False
    try:
        if hasattr(model, 'async_loop') and model.async_loop and not model.async_loop.is_closed():
            try:
                model.async_loop.call_soon_threadsafe(model.async_loop.stop)
                start_time = time.time()
                while model.async_loop.is_running() and time.time() - start_time < SHUTDOWN_JOIN_TIMEOUT:
                    time.sleep(0.2)
                if not model.async_loop.is_closed():
                    model.async_loop.close()
                    logging.info(f"{datetime.now()} - Async loop kapatıldı.")
                else:
                    logging.info(f"{datetime.now()} - Async loop zaten kapalı.")
            except Exception as inner_e:
                logging.error(f"{datetime.now()} - Async loop durdurulurken iç hata: {inner_e}")
                resources_closed = False
    except Exception as e:
        logging.error(f"{datetime.now()} - Async loop kapatılırken hata oluştu: {e}")
        resources_closed = False
    try:
        if hasattr(model, 'async_loop_thread') and model.async_loop_thread:
            if model.async_loop_thread.is_alive():
                logging.info(f"{datetime.now()} - Async loop thread'inin sonlanması bekleniyor.")
                model.async_loop_thread.join(timeout=SHUTDOWN_JOIN_TIMEOUT)
                if model.async_loop_thread.is_alive():
                    logging.warning(f"{datetime.now()} - Async loop thread hala aktif, ikinci join denemesi yapılıyor.")
                    model.async_loop_thread.join(timeout=SHUTDOWN_JOIN_TIMEOUT)
                if model.async_loop_thread.is_alive():
                    logging.error(f"{datetime.now()} - Async loop thread kapatılamadı.")
                    resources_closed = False
                else:
                    logging.info(f"{datetime.now()} - Async loop thread sonlandırıldı.")
    except Exception as e:
        logging.error(f"{datetime.now()} - Async loop thread kapanırken hata oluştu: {e}")
        resources_closed = False
    remaining_threads = []
    for thread in threading.enumerate():
        if thread is not threading.main_thread() and not thread.daemon:
            try:
                logging.info(f"{datetime.now()} - Thread {thread.name} için join bekleniyor.")
                thread.join(timeout=SHUTDOWN_JOIN_TIMEOUT)
                if thread.is_alive():
                    logging.warning(f"{datetime.now()} - Thread {thread.name} hala aktif, ikinci join denemesi yapılıyor.")
                    thread.join(timeout=SHUTDOWN_JOIN_TIMEOUT)
                if thread.is_alive():
                    logging.error(f"{datetime.now()} - Thread {thread.name} kapatılamadı.")
                    remaining_threads.append(thread.name)
                    resources_closed = False
                else:
                    logging.info(f"{datetime.now()} - Thread {thread.name} sonlandı.")
            except Exception as e:
                logging.error(f"{datetime.now()} - Thread {thread.name} kapanırken hata oluştu: {e}")
                resources_closed = False
    if remaining_threads:
        logging.warning(f"{datetime.now()} - Sonlandırılamayan threadler: {', '.join(remaining_threads)}")
    
    if resources_closed:
        logging.info(f"{datetime.now()} - Tüm kaynaklar başarıyla kapatıldı.")
    else:
        logging.warning(f"{datetime.now()} - Bazı kaynaklar düzgün kapatılamadı. Detaylar için log dosyasını kontrol edin.")
    logging.info(f"{datetime.now()} - Graceful shutdown tamamlandı.")
    sys.exit(0)

if __name__ == "__main__":
    base_dir = os.getcwd()
    if not os.path.exists(base_dir):
        os.makedirs(base_dir, exist_ok=True)
    model = IftarModel(base_dir=base_dir, default_timeout=10, short_timeout=5, default_retries=3, backoff_factor=2)
    DEVELOPER_MODE = (model.config_manager.get("DEVELOPER_MODE", "False").lower() == "true")
    CHECK_MODULE_UPDATES = (model.config_manager.get("check_module_updates", "False").lower() == "true")
    if CHECK_MODULE_UPDATES:
        ModuleManager.ensure_required_modules(required_modules)
    else:
        logging.info("Açılışta modül güncellemeleri kontrolü devre dışı bırakıldı.")
    controller = IftarController(model=model)
    view = IftarView(controller=controller, model=model)
    controller.set_view(view)
    def handle_signal(signum, frame):
        logging.info(f"{datetime.now()} - Graceful shutdown başlatılıyor (signal: {signum})")
        graceful_shutdown()
    signal_mod.signal(signal_mod.SIGINT, handle_signal)
    try:
        signal_mod.signal(signal_mod.SIGTERM, handle_signal)
    except AttributeError:
        logging.warning("SIGTERM bu platformda desteklenmiyor.")
    controller.run()
