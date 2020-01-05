#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "etherbone.h"
#include "generated/csr.h"

static struct eb_connection *eb;

uint32_t csr_readl(unsigned long addr) {
    return eb_read32(eb, addr);
}

void csr_writel(uint32_t val, unsigned long addr) {
    eb_write32(eb, val, addr);
}

int main(int argc, char **argv) {
    eb = eb_connect("127.0.0.1", "1234", 0);
    if (!eb) {
        fprintf(stderr, "Couldn't connect\n");
        exit(1);
    }

    touch_capen_write(0xf);
    touch_cper_write(524288);

    while (1) {
        uint8_t c1 = touch_c1_read();
        uint8_t c2 = touch_c2_read();
        uint8_t c3 = touch_c3_read();
        uint8_t c4 = touch_c4_read();

        fprintf(stderr, "%02x %02x %02x %02x\r", c1, c2, c3, c4);
    }
    return 0;
}
