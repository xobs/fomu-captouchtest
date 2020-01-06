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

    touch_ev_enable_write(0);

    touch_capen_write(0xff);
    // touch_capen_write(0);
    // touch_o_write(0);
    // touch_oe_write(0);

#ifdef CSR_TOUCH_CPER_ADDR
    touch_cper_write(524288);
    touch_cpress_write(0x08);
    touch_crel_write(0x02);
#endif

    while (1) {
        fprintf(stderr, "\r");

#ifdef CSR_TOUCH_C1_ADDR
        uint8_t c1 = touch_c1_read();
        uint8_t c2 = touch_c2_read();
        uint8_t c3 = touch_c3_read();
        uint8_t c4 = touch_c4_read();
        fprintf(stderr, "%02x %02x %02x %02x  ", c1, c2, c3, c4);
#endif

        uint8_t evp = touch_ev_pending_read();
        uint8_t stat = touch_cstat_read();
        uint8_t in = touch_i_read();
        uint8_t out = touch_o_read();
        uint8_t oe = touch_oe_read();
        fprintf(stderr, "EV_PEND: %02x  Status: %02x  In: %02x / %02x / %02x", evp, stat, in, out, oe);
        if (evp) {
            unsigned int i;
            fprintf(stderr, "   STATE:");
            touch_ev_pending_write(evp);
            for (i = 0; i < 4; i++)
                fprintf(stderr, " %c", (stat&(1<<i)) ? 'x':' ');
            fprintf(stderr, "\n");
        }
    }
    return 0;
}
