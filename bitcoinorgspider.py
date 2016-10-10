import copy
import os
import sqlite3
from urllib.request import urlopen

from bs4 import BeautifulSoup

OUTDIR = 'Documents/out'

class BitcoinOrgParser(object):
    def __init__(self):
        self.ids = {'reference': {}, 'guide': {}}
        self.glossary = {}
        self.files = {}
        self.headers = {}
        try:
            os.unlink('docSet.dsidx')
        except FileNotFoundError:
            pass
        self.db = sqlite3.connect('docSet.dsidx')
        self.db.execute(
            'CREATE TABLE searchIndex('
                'id INTEGER PRIMARY KEY, name TEXT, type TEXT, path TEXT'
            ')'
        )
        self.db.execute(
            'CREATE UNIQUE INDEX anchor ON searchIndex (name, type, path)'
        )
        self.db.execute('BEGIN')

    def add_to_index(self, type, term, url):
        self.db.execute(
            'INSERT INTO searchIndex(name, type, path) VALUES(?, ?, ?) ',
            (term, type, url.replace('Documents/', ''))
        )
    
    def create_doc(self, items, root='../'):
        ret = BeautifulSoup('<html></html>', 'html.parser').html
        body = BeautifulSoup(
            '<body><style>body { margin: 3em; }</style></body>', 'html.parser'
        )
        for item in items:
            body.append(item)
        ret.append(copy.copy(self.head))
        if root:
            ret.contents[-1]('link')[1]['href'] = (
                root + ret.contents[-1]('link')[1]['href']
            )
        ret.append(body)
        return ret
    
    def extract_until_next(self, h2, prepend=None):
        items = [prepend, h2] if prepend else [h2]
        for ns in h2.next_siblings:
            if ns.name == 'h2':
                break
                
            if (not isinstance(ns, str) and
                    'subhead-links' in ns.get('class', [])):
                continue
            items.append(ns)
        return self.create_doc(items)
      
    def readwrite(self, path):
        data = urlopen('http://127.0.0.1:4000' + path).read()
        try:
            os.makedirs(OUTDIR + '/'.join(path.split('/')[:-1]))
        except FileExistsError:
            pass
        with open(OUTDIR + path, 'wb') as f:
            f.write(data)
      
    def process_file(self, f, name, part=None):
        for tag in f.contents:
            
            if isinstance(tag, str):
                continue
            
            for img in tag('img'):
                if not os.path.isfile(OUTDIR + img['src']):
                    self.readwrite('/'+img['src'])
                img['src'] = '../'+img['src']
            
            if part:
                if 'id' in tag:
                    self.ids[part][tag['id']] = name
                
                for anytag in tag.find_all(id=True):
                    self.ids[part][anytag['id']] = name
      
    def replace_glossary_terms(self, doc, root='../'):
        for tag in doc.contents:
            if isinstance(tag, str):
                continue
            if len(getattr(tag, 'contents', [])):
                self.replace_glossary_terms(tag, root)
            for hreftag in tag.find_all(href=True):
                if hreftag['href'].startswith('/en/glossary'):
                    name = hreftag['href'].split('glossary/', 1)[1]
                    self.process_glossary(name)
                    hreftag['href'] = root + 'glossary/' + name + '.html'
                if hreftag['href'] == '/en/developer-glossary':
                    self.process_glossary('')
                    hreftag['href'] = root + 'glossary/__index.html'
      
    def process_glossary(self, name):
        if name in self.glossary:
            return
        if name:
            url = 'http://127.0.0.1:4000/en/glossary/' + name
            filename = name
            type = 'Word'
        else:
            url = 'http://127.0.0.1:4000/en/developer-glossary'
            filename = '__index'
            term = 'Glossary'
            type = 'Guide'
        soup = BeautifulSoup(urlopen(url).read(), 'html.parser')
        if name:
            term = soup('h1')[0].text
        self.glossary[name] = g = self.create_doc(
            [soup.find(id='content')]
        )
        g.contents[1]('p')[0].extract()
        if name:
            g.contents[1](class_='subhead-links')[0].extract()
        else:
            g.contents[1](class_='notice')[0].extract()
        seen = set()
        if not name:
            for li in g.contents[1]('li'):
                if li.a and li.a.text and li.a.text in seen:
                    li.extract()
                elif li.a and li.a.text:
                    seen.add(li.a.text)
        try:
            os.makedirs(OUTDIR + '/glossary')
        except FileExistsError:
            pass
        self.replace_glossary_terms(self.glossary[name])
        
        self.add_to_index(type, term, OUTDIR + '/glossary/'+filename+'.html')
      
    def process_file_step2(self, f, name, root='../', do_glossary=True):
        if do_glossary:
            self.replace_glossary_terms(f)
        for tag in f.contents:
            if isinstance(tag, str):
                continue
            if len(getattr(tag, 'contents', [])):
                self.process_file_step2(tag, name, root)
            for hreftag in tag.find_all(href=True):
                if hreftag['href'].startswith('/en/developer-reference#'):
                    hash = hreftag['href'].split('#')[1]
                    hreftag['href'] = root+'reference/'+self.ids['reference'][hash]+'.html#'+hash
                if hreftag['href'].startswith('/en/developer-guide#'):
                    hash = hreftag['href'].split('#')[1]
                    hreftag['href'] = root+'guide/'+self.ids['guide'][hash]+'.html#'+hash
      
    @staticmethod
    def parse():
        self = BitcoinOrgParser()
        
        for line in open('../_includes/devdoc/bitcoin-core/rpcs/quick-ref.md'):
            if line.startswith('* '):
                name = line.split('][')[1].split(']')[0].split(' ')[1]
                self.add_to_index('Procedure', name, OUTDIR+'/reference/bitcoin-core-apis.html#'+name)                
                
        for line in open('../_includes/devdoc/bitcoin-core/rest/quick-reference.md'):
            if line.startswith('* '):
                name = line.split('][')[1].split(']')[0].replace('rest ', '')
                verb, name = name.split(' ')
                fullname = verb.upper() + ' ' + name[0].upper() + name[1:]
                shortname = verb + '-' + name
                self.add_to_index('Procedure', fullname, OUTDIR+'/reference/bitcoin-core-apis.html#'+shortname)
                
        self.process1('guide')
        self.process1('reference')
        self.process2('guide')
        self.process2('reference')
        
        self.db.execute('commit')
        
    def process1(self, part):
        soup = BeautifulSoup(
            urlopen('http://127.0.0.1:4000/en/developer-'+part), 'html.parser'
        )
        self.head = soup.head
                
        for css in self.head.link:
            if isinstance(css, str):
                continue
            if css.get('rel', [''])[0] == 'stylesheet':
                self.readwrite(css['href'])
                css['href'] = css['href'].strip('/')
        
        files = self.files[part] = {}
        headers = self.headers[part] = {}
        
        files['introduction'] = self.extract_until_next(
            soup.find(id='content')('p')[2],
            prepend=BeautifulSoup(
                ('<h1 id="bitcoin-developer-reference">'
                 'Bitcoin Developer %s</h1>')%('Guide' if part=='guide' else 'Reference',),
                'html.parser'
            ).h1
        )
        headers['introduction'] = 'Developer Guide' if part=='guide' else 'Developer Reference'
        
        for h in soup.find(id='content')('h2'):
            cur = self.extract_until_next(h)
            files[h['id']] = cur
            headers[h['id']] = h.text + (' Guide' if part=='guide' else ' Reference')
            
        for k, v in files.items():
            self.process_file(v, k, part=part)
            
    def process2(self, part):
        files = self.files[part]
        headers = self.headers[part]
        
        for k, v in files.items():
            self.process_file_step2(v, k)
            
            self.add_to_index('Guide', headers[k], OUTDIR+'/'+part+'/'+k+'.html')
                
        for k, v in files.items():
            with open(OUTDIR + '/' + part + '/' + k + '.html', 'w') as f:
                f.write(str(v))
                
        for k, v in self.glossary.items():
            filename = k or '__index'
            self.process_file(self.glossary[k], k)
            self.process_file_step2(self.glossary[k], k, do_glossary=False)
            with open(OUTDIR + '/glossary/'+filename+'.html', 'wb') as f:
                f.write(str(self.glossary[k]).encode('utf-8'))
    
if __name__ == '__main__':
    BitcoinOrgParser.parse()
