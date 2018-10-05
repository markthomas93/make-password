import sys
import subprocess
import io
import re
import threading
from contextlib import ExitStack

boilerplate = """### Generated file. DO NOT EDIT.
"""

class Sexp:
    regex = re.compile(r"""     (?P<space>\s+)|
                                (?P<lparen>\()|
                                (?P<rparen>\))|
                                (?P<str>"[^"]*")|
                                (?P<token>[^\s][^\s()]*)|
                                (?P<end>\Z)""", re.A | re.X)

    @classmethod
    def _raiseerror(self, s, pos, e):
        raise ValueError("sexp parse error ({}) as {!r} ##HERE## {!r}".format(pos, s[0:pos], s[pos:]))

    @classmethod
    def _token(self, s, pos):
        mo = self.regex.match(s, pos=pos)
        if not mo:
            self._raiseerror(s, pos, 0)
        k = mo.lastgroup
        v = mo.group(k)
#        print(repr((pos, k, v)))
        if k == 'space':
            return self._token(s, mo.end())
#        if k == 'token' and re.match("\A\d+\Z", v):
#            k = 'num'
        return k, v, mo.end()
    
    @classmethod
    def _get(self, s, pos, allowed=()):
        k, v, nextpos = self._token(s, pos)
        if k == 'lparen':
            return self._get_list_to_rparen(s, nextpos)
        elif k in ('token', 'num', 'str') or k in allowed:
            return k, v, nextpos
        else:
            self._raiseerror(s, pos, 1)

    @classmethod
    def _get_list_to_rparen(self, s, pos):
        o = []
        while True:
            k, v, nextpos = self._get(s, pos, ('rparen',))
            if k == 'lparen':
                assert(False)
            elif k in ('num', 'token', 'list', 'str'):
                o.append((k, v))
                pos =  nextpos
            elif k == 'rparen':
                break
            else:
                self._raiseerror(s, pos, 2)
        return 'list', o, nextpos

    @classmethod
    def parse_sexp(self, s):
        k, v, pos = self._get(s, 0)
        k2, _, p = self._token(s, pos)
        if k2 != 'end':
            self._raiseerror(s, pos, 'eos detection')
        return k, v

    @classmethod
    def get_sexp_val(self, s):
        l = self.parse_sexp(s)
        def iter(v):
            k, v = v
            if k == 'list':
                return [iter(e) for e in v]
            elif k == 'token' or k == 'str':
                return v
            elif k == 'num':
                return int(v)
            else:
                assert False, 'unknown type'
        return iter(l)

class Romanization:
    dic = """   xa a xi i xu u xe e xo o ka ga ki gi ku gu ke ge ko go
                sa za shi ji su zu se ze so zo ta da chi ji xtsu tsu zu te de to do
                na ni nu ne no ha ba pa hi bi pi fu bu pu he be pe ho bo po
                ma mi mu me mo xya ya xyu yu xyo yo ra ri ru re ro xwa wa wi we wo n vu xka xke""".split()

    @classmethod
    def romanization(self, s):
        dic = self.dic
        l = []
        for ch in s:
            c = ord(ch)
            if (0x30a1 <= c <= 0x30f6):
                c -= 0x30a1
            elif (0x3041 <= c <= 0x3096):
                c -= 0x3041
            elif (c == 0x30fc):
                l.append("-")
                continue
            else:
                l.append("*")
                continue
            l.append(dic[c])
            continue

        l = "".join(l)
        # ix
        l = re.sub(r'([sc]h|j)ixy([aueo])', r'\1\2', l)
        l = re.sub(r'([sc]h|j)ix([e])', r'\1\2', l)
        l = re.sub(r'([kgnhbpmr])ix(y[aueo]|e)', r'\1\2', l)
        # [ueo]x
        l = re.sub(r'([fv]|ts)ux([aieo])', r'\1\2', l)
        l = re.sub(r'([td])ex([i])', r'\1h\2', l)
        l = re.sub(r'([td])ox([u])', r'\1w\2', l)
        l = re.sub(r'ux([aieo])', r'w\1', l)
        # xtsu
        l = re.sub(r'xtsuch', 'tch', l)
        l = re.sub(r'xtsu([kgsztdnhbpfmurwv])', r'\1\1', l)
        l = re.sub(r'xtsu$', r't', l)
        return l

def fname_relative(base, fname):
    if fname == '':
        return base
    if fname[0] == '/':
        return fname
    basename = base.rpartition('/')
    return (basename[0] or '.') + (basename[1] or '/') + fname

def extract_copyright(fname, section, quote = "# "):
    secstart = True
    active = False
    o = []
    with open(fname) as src:
        for line in src:
            l = line.rstrip()
            if l == '':
                secstart = True
                active = False
                continue

            if secstart:
                secstart = False
                active = l.startswith(section)
                continue

            if active:
                if l != '' and l[0] == ' ':
                    l = l[1:]
                if l != '' and l[0] == '.':
                    l = l[1:]
                o.append((quote + l).strip() + "\n")
        if o == []:
            raise ValueError("can't extract copyright from {}: line starting {!r} not found".format(fname, section))
        return "".join(o)

class CorpusConvert:
    @staticmethod
    def kakasi(src, fname, dest, boilerplate):
        buf = []
        pbuf = []
        for line in src:
            line = line.strip()
            if line == '': continue
            if line[0] == '#': continue
            mo = re.match(r'^([a-z\']+) +\[([^ -~]+)\]$', line)
            if mo:
                en, jp = mo.group(1, 2)
                pbuf.append("{} {}".format(len(buf), en))
                buf.append(jp)
            else:
                for w in line.split(' '):
                    mo = re.match(r'^([^ -~]+)$', w)
                    if mo:
                        pbuf.append("{} {}".format(len(buf), w))
                        buf.append(w)
                    else:
                        pass
                        #print("## {}".format(w))

        with ExitStack() as stack:
            p = stack.enter_context(
                subprocess.Popen("kakasi -iutf8 -outf8 -rh -Ja -Ha",
                                 shell=True,
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE))
            def pf():
                for a in pbuf:
                    p.stdin.write(a.encode('utf-8') + b'\n')
                p.stdin.close()

            t = threading.Thread(target=pf, daemon=True)
            t.start()

            src = io.TextIOWrapper(p.stdout, encoding='utf-8', errors='substitute')
            os = {}

            print("#format hinted\n" + boilerplate, sep="", file=dest)

            for line in src:
                line = line.strip()
                mo = re.match(r'^(\d+) ([a-z\']+)$', line)
                if not mo:
                    print("### ", line, file=dest)
                    continue
                n, ro = mo.group(1, 2)
                n = int(n)
#                ro = re.sub(r'n([m])', r'm\1', ro)  # [bpm]
                ro = re.sub(r'\'', r'', ro)
                if ro in os:
                    print("## {}\t{}\t{}".format(ro, buf[n], os[ro]), file=dest)
                else:
                    os[ro] = buf[n]
                    print("{}\t{}".format(ro, buf[n]), file=dest)
#            t.join()

    @staticmethod
    def chasen(src, fname, dest, boilerplate):
        config = {}
        for l in src:
            k, s, v = l.strip().partition(' ')
            if v:
                config[k.strip()] = v.strip()

        dic_fname = fname_relative(fname, config['input'])
        copyright = extract_copyright(fname_relative(fname, config['copyright']), config['copyright_section'])

        includes = config.get('includes', "").split()
        excludes = config.get('excludes', "").split()
        hiragana_penalty = int(config.get('hiragana-penalty', 0))

        with open(dic_fname) as dic:
            words = []
            lno = 0
            for s in dic:
                lno += 1
                try:
                    l = Sexp.get_sexp_val('(' + s + ')')
                    if len(l) != 2:
                        raise ValueError("l!=2")
                    l = [l[0]] + l[1]
                    l = dict(l)
                    k, p, h, cost = l['見出し語'], l['読み'], l['品詞'], 999999
                    f = False
                    g = False
                    if len(includes):
                        for h0 in h:
                            if h0 in includes:
                                f = True
                                break
                    else:
                        f = True
                    if len(excludes):
                        for h0 in h:
                            if h0 in excludes:
                                f = False
                                break
                    if not f:
                        continue
                    if type(k) == list:
                        if len(k) == 2:
                            k, cost = k
                            cost = int(cost)
                        else:
                            raise ValueError("len(k) != 2")
                    if p[0] == '{':
                        p = p[1:].partition('/')[0]

                    nh = 0
                    for c in k:
                        if 'ぁ' <= c < 'ん':
                            nh += 1
                    cost += nh * hiragana_penalty // len(k)
                    
                    r = Romanization.romanization(p)
                    words.append([cost, k, r])
                except ValueError as e:
                    print("### " + s.strip(), file=dest)
                    print("#### " + str(lno) + ": " + repr(e), file=dest)

            print("#format hinted\n" + boilerplate, sep="", file=dest)
            print(copyright, sep="", file=dest)
            wdic = {}
            for cost, k, r in sorted(words):
                if re.search('[a-zA-Zａ-ｚＡ-Ｚァ-ヾ]', k) or '*' in r or '-' in r or 'x' in r or r == '':
                    #print("## {}\t{}".format(r, k), file=dest)
                    continue
                if r not in wdic:
                    wdic[r] = k
                    print("{}\t{}".format(r, k), file=dest)
                else:
                    print("# {}\t{}\t<- {}".format(r, k, wdic.get(r)), file=dest)

    @classmethod
    def convert(self, fname, ofname):
        hdr = ""
        processor = None
        with open(fname) as src:
            with open(fname) as src2:
                while True:
                    ll = src2.readline()
                    l = ll.strip()
                    if (l == '' or l[0] != '#'): break
                    if l != src.readline().strip():
                        assert False

                    (p, s, t) = l.partition(' ')
                    if (p == '#' or p.startswith('##')):
                        hdr += ll
                    elif (p == '#processor'):
                        processor = t
                    else:
                        raise RuntimeError("Unkown header:", p)
            fun = getattr(self, processor)
            with open(ofname, 'w') as dest:
                b = boilerplate + hdr
                fun(src, fname, dest, boilerplate = b)

if __name__ == '__main__':
    CorpusConvert.convert(*sys.argv[1:])
