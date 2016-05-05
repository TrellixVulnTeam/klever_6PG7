#ifndef __VERIFIER_RCV_H
#define __VERIFIER_RCV_H

/* If expr evaluates to zero, ldv_assert() causes a program to reach the error
 * function call like the standard assert().
 */
extern void ldv_assert(int expression);

/* Internal aliases */
/* Proceed ony if a condition is true */
extern void ldv_assume(int expression);

/* Stop analysis */
extern void ldv_stop(void);

/* Check that error has not been found until there. */
extern void ldv_check_final_state(void);

/* Special nondeterministic functions. */
extern int ldv_undef_int(void);
extern void *ldv_undef_ptr(void);
extern unsigned long ldv_undef_ulong(void);

/* Return nondeterministic negative integer number. */
extern int ldv_undef_int_negative(void);

/* Return nondeterministic nonpositive integer number. */
extern int ldv_undef_int_nonpositive(void);

/* Explicit model for GCC function __builin_expect(). Without this model
 * return value of __builtin_expect() will be treated as nondetermined by
 * verifiers.
 */
extern long __builtin_expect(long exp, long c);

/* This function causes the program to exit abnormally. GCC implements this
 * function by using a target-dependent mechanism (such as intentionally
 * executing an illegal instruction) or by calling abort. The mechanism used
 * may vary from release to release so you should not rely on any particular
 * implementation (http://gcc.gnu.org/onlinedocs/gcc/Other-Builtins.html).
 */
extern void __builtin_trap(void);

/* Pointers greater then this number correspond to errors. */
#define LDV_PTR_MAX 2012

#endif /* __VERIFIER_RCV_H */
