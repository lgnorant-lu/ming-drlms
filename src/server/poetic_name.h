#ifndef DRLMS_POETIC_NAME_H
#define DRLMS_POETIC_NAME_H

#include <stddef.h>

int codename_bank_init(const char *path);
int codename_bank_reload(const char *path);
void codename_bank_cleanup(void);

int codename_generate(char *out_name, size_t out_cap, char *out_version,
                      size_t version_cap);

#endif // DRLMS_POETIC_NAME_H
