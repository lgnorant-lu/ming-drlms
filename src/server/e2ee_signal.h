#ifndef E2EE_SIGNAL_H
#define E2EE_SIGNAL_H

#include <signal/signal_protocol.h>

int e2ee_signal_init(void);
signal_context *e2ee_signal_get(void);

#endif /* E2EE_SIGNAL_H */
