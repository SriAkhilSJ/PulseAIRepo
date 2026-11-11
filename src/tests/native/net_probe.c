#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    int port;
    WSADATA wsa;
    SOCKET s;
    struct sockaddr_in addr;
    int rc;
    u_long nonblocking = 1;
    fd_set writefds;
    struct timeval timeout;
    int socket_error = 0;
    int socket_error_len = sizeof(socket_error);

    if (argc != 2) {
        printf("USAGE\n");
        return 64;
    }
    port = atoi(argv[1]);
    rc = WSAStartup(MAKEWORD(2, 2), &wsa);
    if (rc != 0) {
        printf("WSASTARTUP_FAIL=%d\n", rc);
        return 65;
    }
    s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET) {
        printf("SOCKET_FAIL=%d\n", WSAGetLastError());
        WSACleanup();
        return 66;
    }

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((u_short)port);
    addr.sin_addr.s_addr = inet_addr("127.0.0.1");

    ioctlsocket(s, FIONBIO, &nonblocking);
    rc = connect(s, (struct sockaddr *)&addr, sizeof(addr));
    if (rc == SOCKET_ERROR) {
        int connect_error = WSAGetLastError();
        if (connect_error != WSAEWOULDBLOCK) {
            printf("CONNECT_DENIED=%d\n", connect_error);
            closesocket(s);
            WSACleanup();
            return 67;
        }
        FD_ZERO(&writefds);
        FD_SET(s, &writefds);
        timeout.tv_sec = 3;
        timeout.tv_usec = 0;
        rc = select(0, NULL, &writefds, NULL, &timeout);
        if (rc == 0) {
            printf("CONNECT_TIMEOUT\n");
            closesocket(s);
            WSACleanup();
            return 68;
        }
        if (rc == SOCKET_ERROR) {
            printf("SELECT_DENIED=%d\n", WSAGetLastError());
            closesocket(s);
            WSACleanup();
            return 69;
        }
        if (getsockopt(
                s,
                SOL_SOCKET,
                SO_ERROR,
                (char *)&socket_error,
                &socket_error_len) == SOCKET_ERROR) {
            printf("GETSOCKOPT_FAIL=%d\n", WSAGetLastError());
            closesocket(s);
            WSACleanup();
            return 70;
        }
        if (socket_error != 0) {
            printf("CONNECT_DENIED=%d\n", socket_error);
            closesocket(s);
            WSACleanup();
            return 67;
        }
    }

    printf("CONNECT_OK\n");
    closesocket(s);
    WSACleanup();
    return 0;
}
