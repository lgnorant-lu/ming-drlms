#ifndef DRLMS_ROOMS_STATE_H
#define DRLMS_ROOMS_STATE_H

#include "rooms.h"
#include "rooms_internal.h"

// Internal iterator to traverse all room instances safely without exposing
// globals. The callback is invoked with room and instance pointers; both are
// locked during the call. Return 0 to continue, non-zero to stop early. The
// function returns the first non-zero value returned by the callback, or 0 if
// completed.
int rooms_internal_iter_instances(int (*cb)(Room *room, RoomInstance *inst,
                                            void *ud),
                                  void *ud);

#endif // DRLMS_ROOMS_STATE_H
