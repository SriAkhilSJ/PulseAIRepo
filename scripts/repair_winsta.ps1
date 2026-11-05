$logPath = "c:\Users\Administrator\Downloads\CRUSORAI\repair_ps.log"
Add-Content -Path $logPath -Value "repair_winsta.ps1 started"

$csharpCode = @"
using System;
using System.Runtime.InteropServices;

public class WinStaRepair {
    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr GetProcessWindowStation();

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint GetCurrentThreadId();

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr GetThreadDesktop(uint dwThreadId);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr OpenWindowStationW(string lpszWinSta, bool fInherit, uint dwDesiredAccess);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool CloseWindowStation(IntPtr hWinSta);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr OpenDesktopW(string lpszDesktop, uint dwFlags, bool fInherit, uint dwDesiredAccess);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool CloseDesktop(IntPtr hDesktop);

    [DllImport("advapi32.dll", SetLastError = true)]
    public static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(
        string StringSecurityDescriptor, uint StringSDRevision, out IntPtr SecurityDescriptor, IntPtr SecurityDescriptorSize
    );

    [DllImport("advapi32.dll", SetLastError = true)]
    public static extern bool GetSecurityDescriptorDacl(
        IntPtr pSecurityDescriptor, out bool lpbDaclPresent, out IntPtr pDacl, out bool lpbDaclDefaulted
    );

    [DllImport("advapi32.dll", SetLastError = true)]
    public static extern uint SetSecurityInfo(
        IntPtr handle, int ObjectType, uint SecurityInfo, IntPtr psidOwner, IntPtr psidGroup, IntPtr pDacl, IntPtr pSacl
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr LocalFree(IntPtr hMem);

    public static string Fix() {
        try {
            string sddl = "D:(A;OICI;GA;;;WD)(A;OICI;GA;;;SY)(A;OICI;GA;;;BA)(A;OICI;GA;;;IU)";
            IntPtr pSD;
            if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, out pSD, IntPtr.Zero)) {
                return "ConvertStringSecurityDescriptorToSecurityDescriptorW failed: " + Marshal.GetLastWin32Error();
            }
            bool present, defaulted;
            IntPtr pDacl;
            GetSecurityDescriptorDacl(pSD, out present, out pDacl, out defaulted);

            IntPtr hwinsta = GetProcessWindowStation();
            uint err1 = SetSecurityInfo(hwinsta, 7, 4, IntPtr.Zero, IntPtr.Zero, pDacl, IntPtr.Zero);

            IntPtr hw0 = OpenWindowStationW("WinSta0", false, 0x00040000 | 0x00020000 | 0x0000037F);
            uint err_w0 = 999;
            if (hw0 != IntPtr.Zero) {
                err_w0 = SetSecurityInfo(hw0, 7, 4, IntPtr.Zero, IntPtr.Zero, pDacl, IntPtr.Zero);
                CloseWindowStation(hw0);
            }

            uint tid = GetCurrentThreadId();
            IntPtr hdesk = GetThreadDesktop(tid);
            uint err2 = SetSecurityInfo(hdesk, 7, 4, IntPtr.Zero, IntPtr.Zero, pDacl, IntPtr.Zero);

            IntPtr hd0 = OpenDesktopW("Default", 0, false, 0x00040000 | 0x00020000 | 0x000001FF);
            uint err_d0 = 999;
            if (hd0 != IntPtr.Zero) {
                err_d0 = SetSecurityInfo(hd0, 7, 4, IntPtr.Zero, IntPtr.Zero, pDacl, IntPtr.Zero);
                CloseDesktop(hd0);
            }

            LocalFree(pSD);
            return string.Format("SUCCESS: err1={0}, err_w0={1}, err2={2}, err_d0={3}", err1, err_w0, err2, err_d0);
        } catch (Exception ex) {
            return "EXCEPTION: " + ex.ToString();
        }
    }
}
"@

try {
    Add-Type -TypeDefinition $csharpCode
    $res = [WinStaRepair]::Fix()
    Add-Content -Path $logPath -Value $res
} catch {
    Add-Content -Path $logPath -Value "PowerShell Catch: $_"
}

