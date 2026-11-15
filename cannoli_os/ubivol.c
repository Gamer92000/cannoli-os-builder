#define _FILE_OFFSET_BITS 64
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#define UBI_IOCVOLUP _IOW('O', 0, int64_t)
#define UBI_IOCVOLRMBLK _IO('O', 8)
static char sysbase[128];
static void fail(const char *s) { perror(s); exit(1); }
static void require(int ok, const char *s) { if (!ok) { fprintf(stderr,"ubivol: %s\n",s); exit(1); } }
static void attr(const char *key, char *out, size_t n) {
    char p[200]; snprintf(p,sizeof p,"%s/%s",sysbase,key);
    FILE *f=fopen(p,"r"); if (!f) fail(p);
    require(fgets(out,n,f)!=NULL,"empty sysfs attribute"); fclose(f);
    out[strcspn(out,"\r\n")]=0;
}
static int64_t number(const char *key) {
    char s[64],*end; attr(key,s,sizeof s); errno=0;
    long long n=strtoll(s,&end,10);
    require(!errno && !*end && n>=0,"invalid sysfs number"); return n;
}
static void writeall(int fd, const void *b, size_t n) {
    const char *p=b;
    while(n) { ssize_t k=write(fd,p,n); if(k<0 && errno==EINTR)continue; if(k<=0)fail("write"); p+=k; n-=k; }
}
static void readall(int fd, void *b, size_t n) {
    char *p=b;
    while(n) { ssize_t k=read(fd,p,n); if(k<0 && errno==EINTR)continue; if(k<0)fail("read"); require(k>0,"unexpected EOF"); p+=k; n-=k; }
}
static void compare(const char *node, const char *image, int64_t size) {
    int a=open(node,O_RDONLY|O_CLOEXEC), b=open(image,O_RDONLY|O_CLOEXEC);
    if(a<0||b<0)fail("verify open");
    char x[65536],y[65536];
    while(size) { size_t n=size>(int64_t)sizeof x?sizeof x:(size_t)size;
        readall(a,x,n); readall(b,y,n); require(!memcmp(x,y,n),"readback mismatch"); size-=n; }
    close(a); close(b);
}
int main(int argc,char **argv) {
    require(argc==5,"usage: ubivol check|backup|write|verify NODE EXPECTED_NAME FILE");
    const char *cmd=argv[1], *node=argv[2], *name=argv[3], *file=argv[4];
    struct stat st; if(stat(node,&st))fail(node); require(S_ISCHR(st.st_mode),"not a character device");
    snprintf(sysbase,sizeof sysbase,"/sys/dev/char/%u:%u",major(st.st_rdev),minor(st.st_rdev));
    char actual[128]; attr("name",actual,sizeof actual); require(!strcmp(actual,name),"UBI volume name mismatch");
    int64_t used=number("data_bytes"), blocks=number("reserved_ebs"), leb=number("usable_eb_size");
    const int64_t limit=1024LL*1024*1024;
    require(blocks>0 && leb>0 && leb<limit && blocks<limit/leb,"invalid volume geometry");
    int64_t cap=blocks*leb;
    require(used<=cap,"invalid volume data size");

    if(!strcmp(cmd,"backup")) {
        require(used>0 && !number("upd_marker"),"volume has no valid backup data");
        int in=open(node,O_RDONLY|O_CLOEXEC), out=open(file,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);
        if(in<0||out<0)fail("backup open");
        char b[65536]; int64_t left=used;
        while(left) { size_t n=left>(int64_t)sizeof b?sizeof b:(size_t)left; readall(in,b,n); writeall(out,b,n); left-=n; }
        if(fsync(out))fail("backup fsync");
        close(in); close(out); compare(node,file,used); return 0;
    }
    int image=open(file,O_RDONLY|O_CLOEXEC); if(image<0)fail(file);
    if(fstat(image,&st))fail("image stat");
    require(S_ISREG(st.st_mode),"image is not a regular file");
    int64_t size=st.st_size; require(size>0 && size<=cap,"image exceeds volume capacity");
    if(!strcmp(cmd,"check")) { printf("%s: image=%lld capacity=%lld current=%lld\n",name,(long long)size,(long long)cap,(long long)used); close(image); return 0; }
    if(!strcmp(cmd,"verify")) { close(image); require(size<=used,"image longer than volume data"); compare(node,file,size); return 0; }
    require(!strcmp(cmd,"write"),"unknown operation");

    int vol=open(node,O_RDONLY|O_CLOEXEC); if(vol<0)fail(node);
    if(ioctl(vol,UBI_IOCVOLRMBLK,NULL)<0 && errno!=ENOENT && errno!=ENODEV)fail("remove ubiblock (unmount system first)");
    close(vol); vol=open(node,O_RDWR|O_CLOEXEC); if(vol<0)fail(node);
    if(ioctl(vol,UBI_IOCVOLUP,&size))fail("UBI_IOCVOLUP");
    int64_t left=size; char b[65536];
    while(left) { size_t n=left>(int64_t)sizeof b?sizeof b:(size_t)left; readall(image,b,n); writeall(vol,b,n); left-=n; }
    if(fsync(vol))fail("volume fsync");
    close(vol); close(image);
    compare(node,file,size); printf("%s: written and verified %lld bytes\n",name,(long long)size); return 0;
}
