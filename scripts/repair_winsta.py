import sys
import os

log_path = r"c:\Users\Administrator\Downloads\CRUSORAI\repair_exec.log"

def log(msg):
    with open(log_path, "a") as f:
        f.write(msg + "\n")

log(f"repair_winsta.py started with python {sys.executable}")

try:
    import ctypes
    from ctypes import wintypes
    log("ctypes imported successfully")

    advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    user32 = ctypes.WinDLL('user32', use_last_error=True)

    SDDL_REVISION_1 = 1
    # Full access to Everyone (WD), SYSTEM (SY), Built-in Admins (BA), Interactive (IU)
    sddl = "D:(A;OICI;GA;;;WD)(A;OICI;GA;;;SY)(A;OICI;GA;;;BA)(A;OICI;GA;;;IU)"
    p_sd = ctypes.c_void_p()

    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.ULONG)
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL

    ret = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, SDDL_REVISION_1, ctypes.byref(p_sd), None
    )
    log(f"ConvertStringSD: {ret}")

    p_dacl = ctypes.c_void_p()
    dacl_present = wintypes.BOOL()
    dacl_defaulted = wintypes.BOOL()
    advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)
    ]
    advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi32.GetSecurityDescriptorDacl(p_sd, ctypes.byref(dacl_present), ctypes.byref(p_dacl), ctypes.byref(dacl_defaulted))

    advapi32.SetSecurityInfo.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
    ]
    advapi32.SetSecurityInfo.restype = wintypes.DWORD

    # 1. Process WindowStation
    hwinsta = user32.GetProcessWindowStation()
    err1 = advapi32.SetSecurityInfo(hwinsta, 7, 4, None, None, p_dacl, None)
    log(f"SetSecurityInfo hwinsta: {err1}")

    # 2. Open WinSta0
    user32.OpenWindowStationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
    user32.OpenWindowStationW.restype = wintypes.HANDLE
    user32.CloseWindowStation.argtypes = [wintypes.HANDLE]
    user32.CloseWindowStation.restype = wintypes.BOOL

    h_winsta0 = user32.OpenWindowStationW("WinSta0", False, 0x00040000 | 0x00020000 | 0x0000037F)
    err_w0 = -1
    if h_winsta0:
        err_w0 = advapi32.SetSecurityInfo(h_winsta0, 7, 4, None, None, p_dacl, None)
        user32.CloseWindowStation(h_winsta0)
    log(f"SetSecurityInfo h_winsta0: {err_w0}")

    # 3. Thread Desktop
    hdesk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    err2 = advapi32.SetSecurityInfo(hdesk, 7, 4, None, None, p_dacl, None)
    log(f"SetSecurityInfo hdesk: {err2}")

    # 4. Open Default Desktop
    user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenDesktopW.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL

    h_desk0 = user32.OpenDesktopW("Default", 0, False, 0x00040000 | 0x00020000 | 0x000001FF)
    err_d0 = -1
    if h_desk0:
        err_d0 = advapi32.SetSecurityInfo(h_desk0, 7, 4, None, None, p_dacl, None)
        user32.CloseDesktop(h_desk0)
    log(f"SetSecurityInfo h_desk0: {err_d0}")

    kernel32.LocalFree(p_sd)
    log("SUCCESS: WinSta0 and Default Desktop restored!")
except Exception as e:
    log(f"EXCEPTION: {e}")

