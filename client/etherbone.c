#include <stdio.h>
#include <endian.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/types.h>
#include <errno.h>
#include <stdlib.h>
#include <netdb.h>
#include <sys/socket.h>
#include <netinet/in.h>

#include "etherbone.h"

struct eb_connection {
    int fd;
    int read_fd;
    int is_direct;
    struct addrinfo* addr;
};

int eb_unfill_read32(uint8_t wb_buffer[20]) {
    int buffer;
    uint32_t intermediate;
    memcpy(&intermediate, &wb_buffer[16], sizeof(intermediate));
    intermediate = be32toh(intermediate);
    memcpy(&buffer, &intermediate, sizeof(intermediate));
    return buffer;
}

int eb_fill_readwrite32(uint8_t wb_buffer[20], uint32_t data, uint32_t address, int is_read) {
    memset(wb_buffer, 0, 20);
    wb_buffer[0] = 0x4e;	// Magic byte 0
    wb_buffer[1] = 0x6f;	// Magic byte 1
    wb_buffer[2] = 0x10;	// Version 1, all other flags 0
    wb_buffer[3] = 0x44;	// Address is 32-bits, port is 32-bits
    wb_buffer[4] = 0;		// Padding
    wb_buffer[5] = 0;		// Padding
    wb_buffer[6] = 0;		// Padding
    wb_buffer[7] = 0;		// Padding

    // Record
    wb_buffer[8] = 0;		// No Wishbone flags are set (cyc, wca, wff, etc.)
    wb_buffer[9] = 0x0f;	// Byte enable

    if (is_read) {
        wb_buffer[10] = 0;  // Write count
        wb_buffer[11] = 1;	// Read count
        data = htobe32(address);
        memcpy(&wb_buffer[16], &data, sizeof(data));
    }
    else {
        wb_buffer[10] = 1;	// Write count
        wb_buffer[11] = 0;  // Read count
        address = htobe32(address);
        memcpy(&wb_buffer[12], &address, sizeof(address));

        data = htobe32(data);
        memcpy(&wb_buffer[16], &data, sizeof(data));
    }
    return 20;
}

int eb_fill_write32(uint8_t wb_buffer[20], uint32_t data, uint32_t address) {
    return eb_fill_readwrite32(wb_buffer, data, address, 0);
}

int eb_fill_read32(uint8_t wb_buffer[20], uint32_t address) {
    return eb_fill_readwrite32(wb_buffer, 0, address, 1);
}

int eb_send(struct eb_connection *conn, const void *bytes, size_t len) {
    if (conn->is_direct)
        return sendto(conn->fd, bytes, len, 0, conn->addr->ai_addr, conn->addr->ai_addrlen);
    return write(conn->fd, bytes, len);
}

int eb_recv(struct eb_connection *conn, void *bytes, size_t max_len) {
    if (conn->is_direct)
        return recvfrom(conn->read_fd, bytes, max_len, 0, NULL, NULL);
    return read(conn->fd, bytes, max_len);
}

void eb_write32(struct eb_connection *conn, uint32_t val, uint32_t addr) {
    uint8_t raw_pkt[20];
    eb_fill_write32(raw_pkt, val, addr);
    eb_send(conn, raw_pkt, sizeof(raw_pkt));
}

uint32_t eb_read32(struct eb_connection *conn, uint32_t addr) {
    uint8_t raw_pkt[20];
    eb_fill_read32(raw_pkt, addr);

    eb_send(conn, raw_pkt, sizeof(raw_pkt));

    int count = eb_recv(conn, raw_pkt, sizeof(raw_pkt));
    if (count != sizeof(raw_pkt)) {
        fprintf(stderr, "unexpected read length: %d\n", count);
        return -1;
    }
    return eb_unfill_read32(raw_pkt);
}

struct eb_connection *eb_connect(const char *addr, const char *port, int is_direct) {

    struct addrinfo hints;
    struct addrinfo* res = 0;
    int err;
    int sock;

    struct eb_connection *conn = malloc(sizeof(struct eb_connection));
    if (!conn) {
        perror("couldn't allocate memory for eb_connection");
        return NULL;
    }

    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_INET;
    hints.ai_socktype = is_direct ? SOCK_DGRAM : SOCK_STREAM;
    hints.ai_protocol = is_direct ? IPPROTO_UDP : IPPROTO_TCP;
    hints.ai_flags = AI_ADDRCONFIG;
    err = getaddrinfo(addr, port, &hints, &res);
    if (err != 0) {
        fprintf(stderr, "failed to resolve remote socket address (err=%d / %s)\n", err, gai_strerror(err));
        free(conn);
        return NULL;
    }

    conn->is_direct = is_direct;

    if (is_direct) {
        // Rx half
        struct sockaddr_in si_me;

        memset((char *) &si_me, 0, sizeof(si_me));
        si_me.sin_family = res->ai_family;
        si_me.sin_port = ((struct sockaddr_in *)res->ai_addr)->sin_port;
        si_me.sin_addr.s_addr = htobe32(INADDR_ANY);

        int rx_socket;
        if ((rx_socket = socket(res->ai_family, res->ai_socktype, res->ai_protocol)) == -1) {
            fprintf(stderr, "Unable to create Rx socket: %s\n", strerror(errno));
            freeaddrinfo(res);
            free(conn);
            return NULL;
        }
        if (bind(rx_socket, (struct sockaddr*)&si_me, sizeof(si_me)) == -1) {
            fprintf(stderr, "Unable to bind Rx socket to port: %s\n", strerror(errno));
            close(rx_socket);
            freeaddrinfo(res);
            free(conn);
            return NULL;
        }

        // Tx half
        int tx_socket = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
        if (tx_socket == -1) {
            fprintf(stderr, "Unable to create socket: %s\n", strerror(errno));
            close(rx_socket);
            close(tx_socket);
            freeaddrinfo(res);
            fprintf(stderr, "unable to create socket: %s\n", strerror(errno));
            free(conn);
            return NULL;
        }

        conn->read_fd = rx_socket;
        conn->fd = tx_socket;
        conn->addr = res;
    }
    else {
        sock = socket(AF_INET, SOCK_STREAM, 0);
        if (sock == -1) {
            fprintf(stderr, "failed to create socket: %s\n", strerror(errno));
            freeaddrinfo(res);
            free(conn);
            return NULL;
        }

        int connection = connect(sock, res->ai_addr, res->ai_addrlen);
        if (connection == -1) {
            close(sock);
            freeaddrinfo(res);
            fprintf(stderr, "unable to create socket: %s\n", strerror(errno));
            free(conn);
            return NULL;
        }

        conn->fd = sock;
        conn->addr = res;
    }

    return conn;
}

void eb_disconnect(struct eb_connection **conn) {
    if (!conn || !*conn)
        return;

    freeaddrinfo((*conn)->addr);
    close((*conn)->fd);
    if ((*conn)->read_fd)
        close((*conn)->read_fd);
    free(*conn);
    *conn = NULL;
    return;
}

#if 0
#if CSR_WIDTH == 8
void csr_write8(struct wb_connection *conn, uint32_t addr, uint8_t val) {
    uint8_t raw_pkt[20];
    struct etherbone_packet *pkt = (struct etherbone_packet *)raw_pkt;
    wb_fillpkt(raw_pkt, 0, 1);

    pkt->records[0].write_addr = htobe32(addr);
    pkt->records[0].value = htobe32(val & 0xff);

    wb_send(conn, raw_pkt, 20);
}

void csr_write16(struct wb_connection *conn, uint32_t addr, uint16_t val) {
    val = htole16(val);
    int i;
    for (i = 0; i < 2; i++)
        csr_write8(conn, addr + (i * 4), val >> ((1 - i) * 8));
}

void csr_write32(struct wb_connection *conn, uint32_t addr, uint32_t val) {
    val = htole32(val);
    int i;
    for (i = 0; i < 4; i++)
        csr_write8(conn, addr + (i * 4), val >> ((3 - i) * 8));
}

void csr_write64(struct wb_connection *conn, uint32_t addr, uint64_t val) {
    val = htole64(val);
    int i;
    for (i = 0; i < 8; i++)
        csr_write8(conn, addr + (i * 4), val >> ((7 - i) * 8));
}

uint8_t csr_read8(struct wb_connection *conn, uint32_t addr) {
    uint8_t raw_pkt[20];
    struct etherbone_packet *pkt = (struct etherbone_packet *)raw_pkt;
    wb_fillpkt(raw_pkt, 1, 0);
    pkt->records[0].value = htobe32(addr);

    wb_send(conn, raw_pkt, sizeof(raw_pkt));

    int count = wb_recv(conn, raw_pkt, sizeof(raw_pkt));
    if (count != sizeof(raw_pkt)) {
        fprintf(stderr, "Unexpected read length: %d\n", count);
        return -1;
    }
    return be32toh(pkt->records[0].value) & 0xff;
}

uint16_t csr_read16(struct wb_connection *conn, uint32_t addr) {
    uint16_t val = 0;
    int i;
    for (i = 0; i < 2; i++)
        val |= ((uint16_t)csr_read8(conn, addr + (i * 4))) << ((1 - i) * 8);
    return le16toh(val);
}

uint32_t csr_read32(struct wb_connection *conn, uint32_t addr) {
    uint32_t val = 0;
    int i;
    for (i = 0; i < 4; i++)
        val |= ((uint32_t)csr_read8(conn, addr + (i * 4))) << ((3 - i) * 8);
    return le32toh(val);
}

uint64_t csr_read64(struct wb_connection *conn, uint32_t addr) {
    uint64_t val = 0;
    int i;
    for (i = 0; i < 8; i++)
        val |= ((uint64_t)csr_read8(conn, addr + (i * 4))) << ((7 - i) * 8);
    return le64toh(val);
}

#elif CSR_WIDTH == 32

void csr_write32(struct wb_connection *conn, uint32_t addr, uint32_t val) {
    uint8_t raw_pkt[20];
    struct etherbone_packet *pkt = (struct etherbone_packet *)raw_pkt;
    wb_fillpkt(raw_pkt, 0, 1);

    pkt->records[0].write_addr = htobe32(addr);
    pkt->records[0].value = htobe32(val);

    wb_send(conn, raw_pkt, 20);
}

void csr_write16(struct wb_connection *conn, uint32_t addr, uint16_t val) {
    csr_write32(conn, addr, val & 0xffff);
}

void csr_write8(struct wb_connection *conn, uint32_t addr, uint8_t val) {
    csr_write32(conn, addr, val & 0xff);
}

void csr_write64(struct wb_connection *conn, uint32_t addr, uint64_t val) {
    val = htole64(val);
    int i;
    for (i = 0; i < 2; i++)
        csr_write32(conn, addr + (i * 4), val >> ((1 - i) * 8));
}

uint32_t csr_read32(struct wb_connection *conn, uint32_t addr) {
    uint8_t raw_pkt[20];
    struct etherbone_packet *pkt = (struct etherbone_packet *)raw_pkt;
    wb_fillpkt(raw_pkt, 1, 0);
    pkt->records[0].value = htobe32(addr);

    wb_send(conn, raw_pkt, sizeof(raw_pkt));

    int count = wb_recv(conn, raw_pkt, sizeof(raw_pkt));
    if (count != sizeof(raw_pkt)) {
        fprintf(stderr, "Unexpected read length: %d\n", count);
        return -1;
    }
    return be32toh(pkt->records[0].value);
}

uint16_t csr_read16(struct wb_connection *conn, uint32_t addr) {
    return csr_read32(conn, addr) & 0xffff;
}

uint8_t csr_read8(struct wb_connection *conn, uint32_t addr) {
    return csr_read32(conn, addr) & 0xff;
}

uint64_t csr_read64(struct wb_connection *conn, uint32_t addr) {
    uint64_t val = 0;
    int i;
    for (i = 0; i < 2; i++)
        val |= ((uint64_t)csr_read32(conn, addr + (i * 4))) << ((1 - i) * 8);
    return le64toh(val);
}

#else
#pragma error "Unrecognized CSR width"
#endif
#endif
