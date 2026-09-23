#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <dokan.h>

#include <cstdint>
#include <cstring>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>
#include <algorithm>

#pragma comment(lib, "Ws2_32.lib")

// The Dokan layer talks to the persistent local RAM-Link service.
// Android/RML1 details stay behind ramlink_memory_service.py.
static const char* LOCAL_HOST = "127.0.0.1";
static const uint16_t LOCAL_PORT = 19080;
static const uint32_t MAX_BLOCK = 1024 * 1024;
static const uint32_t SECTOR_SIZE = 512;

static bool send_all(SOCKET s, const void* data, size_t len) {
    const char* p = static_cast<const char*>(data);
    while (len) {
        int n = send(s, p, static_cast<int>(std::min<size_t>(len, 1024 * 1024)), 0);
        if (n <= 0) return false;
        p += n;
        len -= static_cast<size_t>(n);
    }
    return true;
}

static bool recv_all(SOCKET s, void* data, size_t len) {
    char* p = static_cast<char*>(data);
    while (len) {
        int n = recv(s, p, static_cast<int>(std::min<size_t>(len, 1024 * 1024)), 0);
        if (n <= 0) return false;
        p += n;
        len -= static_cast<size_t>(n);
    }
    return true;
}

static bool recv_line(SOCKET s, std::string& line) {
    line.clear();
    char c = 0;
    while (line.size() < 8192) {
        int n = recv(s, &c, 1, 0);
        if (n <= 0) return false;
        if (c == '\n') return true;
        if (c != '\r') line.push_back(c);
    }
    return false;
}

static SOCKET connect_local() {
    addrinfo hints{};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_protocol = IPPROTO_TCP;

    addrinfo* result = nullptr;
    std::string service = std::to_string(LOCAL_PORT);
    if (getaddrinfo(LOCAL_HOST, service.c_str(), &hints, &result) != 0)
        return INVALID_SOCKET;

    SOCKET connected = INVALID_SOCKET;
    for (addrinfo* p = result; p; p = p->ai_next) {
        SOCKET s = socket(p->ai_family, p->ai_socktype, p->ai_protocol);
        if (s == INVALID_SOCKET) continue;

        DWORD timeout = 60000;
        setsockopt(s, SOL_SOCKET, SO_RCVTIMEO,
                   reinterpret_cast<const char*>(&timeout), sizeof(timeout));
        setsockopt(s, SOL_SOCKET, SO_SNDTIMEO,
                   reinterpret_cast<const char*>(&timeout), sizeof(timeout));

        if (connect(s, p->ai_addr, static_cast<int>(p->ai_addrlen)) == 0) {
            connected = s;
            break;
        }
        closesocket(s);
    }
    freeaddrinfo(result);
    return connected;
}

class LocalRamLinkClient {
public:
    uint64_t size() const {
        std::lock_guard<std::mutex> guard(mu_);
        SOCKET s = connect_local();
        if (s == INVALID_SOCKET) return 0;

        const char* command = "SIZE\n";
        bool ok = send_all(s, command, std::strlen(command));
        std::string line;
        if (ok) ok = recv_line(s, line);
        closesocket(s);

        if (!ok) return 0;
        try {
            return std::stoull(line);
        } catch (...) {
            return 0;
        }
    }

    bool read(uint64_t offset, void* out, uint32_t length) {
        if (length > MAX_BLOCK) return false;

        std::lock_guard<std::mutex> guard(mu_);
        SOCKET s = connect_local();
        if (s == INVALID_SOCKET) return false;

        std::string command = "READ " + std::to_string(offset) + " " +
                              std::to_string(length) + "\n";
        if (!send_all(s, command.data(), command.size())) {
            closesocket(s);
            return false;
        }

        uint32_t net_length = 0;
        if (!recv_all(s, &net_length, sizeof(net_length))) {
            closesocket(s);
            return false;
        }

        uint32_t response = ntohl(net_length);
        bool ok = response == length;
        if (ok && length) ok = recv_all(s, out, length);
        closesocket(s);
        return ok;
    }

    bool write(uint64_t offset, const void* data, uint32_t length) {
        if (length > MAX_BLOCK) return false;

        std::lock_guard<std::mutex> guard(mu_);
        SOCKET s = connect_local();
        if (s == INVALID_SOCKET) return false;

        std::string command = "WRITE " + std::to_string(offset) + " " +
                              std::to_string(length) + "\n";
        if (!send_all(s, command.data(), command.size())) {
            closesocket(s);
            return false;
        }
        if (length && !send_all(s, data, length)) {
            closesocket(s);
            return false;
        }

        std::string response;
        bool ok = recv_line(s, response) && response == "OK";
        closesocket(s);
        return ok;
    }

private:
    mutable std::mutex mu_;
};

static LocalRamLinkClient* g_client = nullptr;
static const wchar_t* RAM_FILE = L"\\RAMLINK.BIN";

static bool is_root(LPCWSTR name) {
    return name && (wcscmp(name, L"\\") == 0 || wcscmp(name, L"") == 0);
}
static bool is_ram_file(LPCWSTR name) {
    return name && _wcsicmp(name, RAM_FILE) == 0;
}
static void fill_file_info(LPBY_HANDLE_FILE_INFORMATION b, uint64_t size, bool directory) {
    ZeroMemory(b, sizeof(*b));
    b->dwFileAttributes = directory ? FILE_ATTRIBUTE_DIRECTORY : FILE_ATTRIBUTE_NORMAL;
    b->nFileSizeHigh = static_cast<DWORD>(size >> 32);
    b->nFileSizeLow = static_cast<DWORD>(size & 0xFFFFFFFFULL);
    b->nNumberOfLinks = 1;
    b->dwVolumeSerialNumber = 0x524D4C31;
}

static NTSTATUS DOKAN_CALLBACK rl_create(
    LPCWSTR FileName, PDOKAN_IO_SECURITY_CONTEXT, ACCESS_MASK, ULONG, ULONG,
    ULONG CreateDisposition, ULONG, PDOKAN_FILE_INFO info) {
    if (is_root(FileName)) {
        info->IsDirectory = TRUE;
        info->Context = 1;
        return STATUS_SUCCESS;
    }
    if (!is_ram_file(FileName)) return STATUS_OBJECT_NAME_NOT_FOUND;
    if (CreateDisposition == CREATE_NEW || CreateDisposition == CREATE_ALWAYS ||
        CreateDisposition == TRUNCATE_EXISTING)
        return STATUS_OBJECT_NAME_COLLISION;
    info->IsDirectory = FALSE;
    info->Context = 2;
    return STATUS_SUCCESS;
}

static void DOKAN_CALLBACK rl_cleanup(LPCWSTR, PDOKAN_FILE_INFO info) { info->Context = 0; }
static void DOKAN_CALLBACK rl_close(LPCWSTR, PDOKAN_FILE_INFO info) { info->Context = 0; }

static NTSTATUS DOKAN_CALLBACK rl_read(
    LPCWSTR FileName, LPVOID Buffer, DWORD BufferLength, LPDWORD ReadLength,
    LONGLONG Offset, PDOKAN_FILE_INFO) {
    *ReadLength = 0;
    if (!is_ram_file(FileName) || Offset < 0 || !g_client)
        return STATUS_OBJECT_NAME_NOT_FOUND;

    uint64_t off = static_cast<uint64_t>(Offset);
    uint64_t total64 = g_client->size();
    if (off >= total64) return STATUS_SUCCESS;

    uint32_t total = static_cast<uint32_t>(
        std::min<uint64_t>(BufferLength, total64 - off));

    uint8_t* p = static_cast<uint8_t*>(Buffer);
    uint32_t done = 0;
    while (done < total) {
        uint32_t n = std::min<uint32_t>(MAX_BLOCK, total - done);
        if (!g_client->read(off + done, p + done, n))
            return STATUS_DEVICE_NOT_CONNECTED;
        done += n;
    }
    *ReadLength = done;
    return STATUS_SUCCESS;
}

static NTSTATUS DOKAN_CALLBACK rl_write(
    LPCWSTR FileName, LPCVOID Buffer, DWORD NumberOfBytesToWrite,
    LPDWORD NumberOfBytesWritten, LONGLONG Offset, PDOKAN_FILE_INFO) {
    *NumberOfBytesWritten = 0;
    if (!is_ram_file(FileName) || Offset < 0 || !g_client)
        return STATUS_OBJECT_NAME_NOT_FOUND;

    uint64_t off = static_cast<uint64_t>(Offset);
    uint64_t total64 = g_client->size();
    if (off > total64 || NumberOfBytesToWrite > total64 - off)
        return STATUS_DISK_FULL;

    const uint8_t* p = static_cast<const uint8_t*>(Buffer);
    uint32_t done = 0;
    while (done < NumberOfBytesToWrite) {
        uint32_t n = std::min<uint32_t>(MAX_BLOCK, NumberOfBytesToWrite - done);
        if (!g_client->write(off + done, p + done, n))
            return STATUS_DEVICE_NOT_CONNECTED;
        done += n;
    }
    *NumberOfBytesWritten = done;
    return STATUS_SUCCESS;
}

static NTSTATUS DOKAN_CALLBACK rl_flush(LPCWSTR, PDOKAN_FILE_INFO) {
    return STATUS_SUCCESS;
}

static NTSTATUS DOKAN_CALLBACK rl_info(
    LPCWSTR FileName, LPBY_HANDLE_FILE_INFORMATION Buffer, PDOKAN_FILE_INFO) {
    if (is_root(FileName)) {
        fill_file_info(Buffer, 0, true);
        return STATUS_SUCCESS;
    }
    if (is_ram_file(FileName) && g_client) {
        uint64_t n = g_client->size();
        if (!n) return STATUS_DEVICE_NOT_CONNECTED;
        fill_file_info(Buffer, n, false);
        return STATUS_SUCCESS;
    }
    return STATUS_OBJECT_NAME_NOT_FOUND;
}

static NTSTATUS DOKAN_CALLBACK rl_find(
    LPCWSTR FileName, PFillFindData FillFindData, PDOKAN_FILE_INFO info) {
    if (!is_root(FileName)) return STATUS_OBJECT_PATH_NOT_FOUND;

    WIN32_FIND_DATAW f{};
    wcscpy_s(f.cFileName, L"RAMLINK.BIN");
    f.dwFileAttributes = FILE_ATTRIBUTE_NORMAL;
    uint64_t size = g_client ? g_client->size() : 0;
    f.nFileSizeHigh = static_cast<DWORD>(size >> 32);
    f.nFileSizeLow = static_cast<DWORD>(size);
    return FillFindData(&f, info) == 0 ? STATUS_SUCCESS : STATUS_BUFFER_OVERFLOW;
}

static NTSTATUS DOKAN_CALLBACK rl_setattr(LPCWSTR, DWORD, PDOKAN_FILE_INFO) {
    return STATUS_SUCCESS;
}
static NTSTATUS DOKAN_CALLBACK rl_settime(
    LPCWSTR, const FILETIME*, const FILETIME*, const FILETIME*, PDOKAN_FILE_INFO) {
    return STATUS_SUCCESS;
}
static NTSTATUS DOKAN_CALLBACK rl_delete_file(LPCWSTR FileName, PDOKAN_FILE_INFO) {
    return is_ram_file(FileName) ? STATUS_ACCESS_DENIED : STATUS_OBJECT_NAME_NOT_FOUND;
}
static NTSTATUS DOKAN_CALLBACK rl_delete_dir(LPCWSTR FileName, PDOKAN_FILE_INFO) {
    return is_root(FileName) ? STATUS_ACCESS_DENIED : STATUS_OBJECT_NAME_NOT_FOUND;
}
static NTSTATUS DOKAN_CALLBACK rl_move(LPCWSTR, LPCWSTR, BOOL, PDOKAN_FILE_INFO) {
    return STATUS_ACCESS_DENIED;
}
static NTSTATUS DOKAN_CALLBACK rl_set_eof(
    LPCWSTR FileName, LONGLONG ByteOffset, PDOKAN_FILE_INFO) {
    if (!is_ram_file(FileName) || !g_client) return STATUS_OBJECT_NAME_NOT_FOUND;
    return ByteOffset == static_cast<LONGLONG>(g_client->size())
        ? STATUS_SUCCESS : STATUS_INVALID_PARAMETER;
}
static NTSTATUS DOKAN_CALLBACK rl_set_alloc(
    LPCWSTR FileName, LONGLONG AllocSize, PDOKAN_FILE_INFO info) {
    return rl_set_eof(FileName, AllocSize, info);
}
static NTSTATUS DOKAN_CALLBACK rl_disk(
    PULONGLONG FreeBytesAvailable, PULONGLONG TotalNumberOfBytes,
    PULONGLONG TotalNumberOfFreeBytes, PDOKAN_FILE_INFO) {
    uint64_t n = g_client ? g_client->size() : 0;
    *FreeBytesAvailable = n;
    *TotalNumberOfBytes = n;
    *TotalNumberOfFreeBytes = n;
    return STATUS_SUCCESS;
}
static NTSTATUS DOKAN_CALLBACK rl_volume(
    LPWSTR VolumeNameBuffer, DWORD VolumeNameSize, LPDWORD Serial,
    LPDWORD MaxComponent, LPDWORD Flags, LPWSTR FsNameBuffer,
    DWORD FsNameSize, PDOKAN_FILE_INFO) {
    if (VolumeNameSize)
        wcsncpy_s(VolumeNameBuffer, VolumeNameSize, L"RAM-Link", _TRUNCATE);
    if (FsNameSize)
        wcsncpy_s(FsNameBuffer, FsNameSize, L"RAMLINK", _TRUNCATE);
    *Serial = 0x524D4C31;
    *MaxComponent = 255;
    *Flags = FILE_CASE_PRESERVED_NAMES | FILE_UNICODE_ON_DISK;
    return STATUS_SUCCESS;
}
static NTSTATUS DOKAN_CALLBACK rl_mounted(LPCWSTR MountPoint, PDOKAN_FILE_INFO) {
    std::wcout << L"Mounted: " << MountPoint << L"\n";
    return STATUS_SUCCESS;
}
static NTSTATUS DOKAN_CALLBACK rl_unmounted(PDOKAN_FILE_INFO) {
    std::wcout << L"Unmounted\n";
    return STATUS_SUCCESS;
}

static DOKAN_OPERATIONS make_ops() {
    DOKAN_OPERATIONS o{};
    o.ZwCreateFile = rl_create;
    o.Cleanup = rl_cleanup;
    o.CloseFile = rl_close;
    o.ReadFile = rl_read;
    o.WriteFile = rl_write;
    o.FlushFileBuffers = rl_flush;
    o.GetFileInformation = rl_info;
    o.FindFiles = rl_find;
    o.SetFileAttributes = rl_setattr;
    o.SetFileTime = rl_settime;
    o.DeleteFile = rl_delete_file;
    o.DeleteDirectory = rl_delete_dir;
    o.MoveFile = rl_move;
    o.SetEndOfFile = rl_set_eof;
    o.SetAllocationSize = rl_set_alloc;
    o.GetDiskFreeSpace = rl_disk;
    o.GetVolumeInformation = rl_volume;
    o.Mounted = rl_mounted;
    o.Unmounted = rl_unmounted;
    return o;
}

int wmain(int argc, wchar_t* argv[]) {
    wchar_t mount[8] = L"R:\\";
    if (argc >= 2) {
        if (wcslen(argv[1]) == 1) {
            mount[0] = argv[1][0]; mount[1] = L':'; mount[2] = L'\\'; mount[3] = 0;
        } else if (wcslen(argv[1]) == 2 && argv[1][1] == L':') {
            mount[0] = argv[1][0]; mount[1] = L':'; mount[2] = L'\\'; mount[3] = 0;
        } else {
            wcscpy_s(mount, argv[1]);
        }
    }

    WSADATA wsa{};
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        std::cerr << "WSAStartup failed\n";
        return 1;
    }

    LocalRamLinkClient client;
    g_client = &client;

    uint64_t n = client.size();
    if (!n) {
        std::cerr << "RAM-Link local service is not available on 127.0.0.1:19080.\n";
        std::cerr << "Start ramlink_memory_service.py first.\n";
        WSACleanup();
        return 2;
    }

    std::cout << "RAM-Link local service connected. Remote RAM: "
              << (n / 1024 / 1024) << " MiB\n";

    DOKAN_OPTIONS opt{};
    opt.Version = DOKAN_VERSION;
    opt.SingleThread = FALSE;
    opt.Options = DOKAN_OPTION_MOUNT_MANAGER;
    opt.MountPoint = mount;
    opt.Timeout = 60000;
    opt.AllocationUnitSize = SECTOR_SIZE;
    opt.SectorSize = SECTOR_SIZE;
    opt.GlobalContext = reinterpret_cast<ULONG64>(&client);

    DOKAN_OPERATIONS ops = make_ops();
    DokanInit();
    int result = DokanMain(&opt, &ops);
    DokanShutdown();

    g_client = nullptr;
    WSACleanup();
    std::cout << "DokanMain result: " << result << "\n";
    return result == DOKAN_SUCCESS ? 0 : 3;
}
