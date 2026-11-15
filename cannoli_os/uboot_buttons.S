.section .text
.balign 4
.global button_hook, product_hook, marker, marker_first, marker_second, marker_state
button_hook:
    stp x29, x30, [sp, #-64]!
    stp x19, x20, [sp, #16]
    stp x21, x22, [sp, #32]
    mov x19, x29
    mov x29, sp
    bl stock_get_active
    mov w20, w0
    adr x21, marker_state
    mov w0, #'E'
    strb w0, [x21]
.if !PROBE
    ldr w0, [x19, #116]
    cbnz w0, priority
.endif
    mov w0, #4
    mov w1, #8
    mov w2, #1
    add x3, sp, #48
    str xzr, [x3]
    bl stock_i2c_get_chip_for_bus
    cbnz w0, done
    ldr x0, [sp, #48]
    cbz x0, done
    mov w1, #0xf0
    add x2, sp, #56
    mov w3, #1
    bl stock_dm_i2c_read
    cbnz w0, done
    ldrb w22, [sp, #56]
    mov w0, w22
    adr x1, marker_first
    bl byte_hex
    mov x0, #20000
    bl stock_udelay
    ldr x0, [sp, #48]
    mov w1, #0xf0
    add x2, sp, #56
    mov w3, #1
    bl stock_dm_i2c_read
    cbnz w0, done
    ldrb w0, [sp, #56]
    adr x1, marker_second
    bl byte_hex
    mov w0, #'N'
    strb w0, [x21]
    and w0, w22, #0x0c
    cmp w0, #0x08
    b.ne done
    ldrb w0, [sp, #56]
    and w0, w0, #0x0c
    cmp w0, #0x08
    b.ne done
    mov w0, #'U'
    strb w0, [x21]
.if !PROBE
    adr x0, boot_variable
    adr x1, recovery_command
    bl stock_env_set
    cbnz w0, env_failure
    mov w20, #1
    mov w0, #1
    str w0, [x19, #120]
    adr x1, stock_recovery_cache
    strb w0, [x1]
.endif
done:
    mov w0, w20
    ldp x19, x20, [sp, #16]
    ldp x21, x22, [sp, #32]
    ldp x29, x30, [sp], #64
    ret
.if !PROBE
priority:
    mov w0, #'P'
    strb w0, [x21]
    b done
env_failure:
    mov w0, #'E'
    strb w0, [x21]
    b done
.endif
byte_hex:
    adr x3, hex_digits
    ubfx w2, w0, #4, #4
    ldrb w2, [x3, x2]
    strb w2, [x1]
    and w2, w0, #15
    ldrb w2, [x3, x2]
    strb w2, [x1, #1]
    ret
product_hook:
    adr x0, marker
    b stock_fastboot_okay
hex_digits: .ascii "0123456789abcdef"
marker: .ascii "cannoli-keys-"
marker_first: .ascii "??-"
marker_second: .ascii "??-"
marker_state: .asciz "?"
boot_variable: .asciz "mtk_boot"
recovery_command:
    .asciz "mw.l ${loadaddr} 0 1;ubi read ${loadaddr} boot_b;bootm ${loadaddr};reset"
