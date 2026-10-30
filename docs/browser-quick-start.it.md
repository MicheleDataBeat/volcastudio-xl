# VolcaStudio XL Browser App: guida rapida

Prepara e invia un kit di campioni con VolcaStudio XL Browser App 1.1.0,
un’applicazione installata sul computer che si apre in Google Chrome. Non serve
il terminale.

## 1. Cosa serve

- Un computer con Windows 10/11 x64, macOS su Apple silicon o Linux x86-64
  (glibc 2.35 o successiva).
- **Google Chrome**, gratuito da google.com/chrome.
- Una **Korg Volca Sample** originale (prima generazione); per pattern e groove
  serve DataBeat OS 1.0. Per installare DataBeat OS 1.0 scarica da korg.com
  l’aggiornamento ufficiale Korg `volcasample_updater_1_42.zip` e aggiungilo
  nella sezione **Firmware** con **Choose the Korg 1.42 updater…**: la Browser App
  crea DataBeat OS 1.0 a partire da quel file e verifica il risultato.
  Studio non contiene firmware.
- Un **cavo audio jack 3,5 mm** dall'uscita cuffie/linea del computer alla presa
  **SYNC IN** della Volca.

## 2. Scarica e apri

1. Nella [pagina di download](https://micheledatabeat.github.io/volcastudio-xl-releases/) premi **Scarica la Browser App**. Controlla che il pacchetto suggerito corrisponda al sistema e all’architettura del computer; **Tutti i download** elenca le alternative.
2. Estrai il download e apri **VolcaStudio XL Browser App**, seguendo le istruzioni per il tuo sistema qui sotto.
3. Il servizio locale apre la Browser App in Chrome. Non devi digitare un indirizzo.

I pacchetti non sono firmati. Verifica il download con `SHA256SUMS` nella
[pagina delle release di VolcaStudio XL](https://github.com/MicheleDataBeat/volcastudio-xl-releases/releases).
Usa l’eccezione di apertura seguente solo per quella copia verificata, se ti fidi.

- **Windows:** tasto destro sullo ZIP → **Estrai tutto** → apri la cartella →
     doppio clic su **VolcaStudio XL Browser App**. Se compare *Windows ha protetto il PC*,
     scegli **Ulteriori informazioni → Esegui comunque** (solo la prima volta).
- **macOS:** apri lo ZIP e trascina **VolcaStudio XL Browser App** in **Applicazioni**,
     poi aprila. Se macOS non può verificare lo sviluppatore, apri
     **Impostazioni di Sistema → Privacy e sicurezza** e scegli **Apri comunque** (solo la prima volta).
- **Linux:** estrai l'archivio, apri la cartella, doppio clic su
     **VolcaStudio XL Browser App** (oppure tasto destro → **Esegui come programma**).

Riaprendo la Browser App si apre un’altra finestra della sessione in corso.

## 3. Scegli i campioni

1. In **01 Gathering** fai clic su **Add samples…** (o **Add a folder…**) e scegli
   i tuoi file WAV. La Browser App conserva le copie importate nella propria cartella
   di libreria. Per usare una cartella senza copiarla, scegli **Manage libraries…**,
   inserisci il percorso completo e premi **Register folder**. La cartella diventa
   disponibile anche nella Desktop App.
2. Fai clic su un campione per selezionarlo. Tieni premuto **Maiusc** per un
   intervallo, **Ctrl** (Windows/Linux) o **⌘** (Mac) per sceglierne diversi.
3. Indirizza **l'uscita audio di Chrome** a casse o cuffie, lontano da **SYNC IN**.
   **Listening source** offre **Source audio** oppure **Volca preview (mono, 31.25 kHz)**.
   Premi **Spazio** per ascoltare; **Stop** ferma la riproduzione. **Autoplay selection**
   ascolta i singoli campioni mentre li selezioni. L'uscita scelta in Connections
   serve ai trasferimenti: non cambia l'uscita di ascolto di Chrome.
4. Premi **Invio** per metterli sul **workbench** (il banco di lavoro).

Scegli **All samples** per cercare in tutte le librerie disponibili, nei kit salvati
e nelle varianti. **Previous page / Next page** mostra gli altri risultati;
**Refresh** aggiorna i file modificati fuori dalla Browser App.
**Manage libraries… → Unregister** rimuove un riferimento, anche se l'unità è
scollegata; lascia i file dove sono.

## 4. Prepara il kit

- Ordina i campioni con **↑ ↓**, **Alt+↑/↓** o trascinandoli.
- Controlla l'indicatore: al massimo **100 campioni** e **65 secondi**.
- Facoltativo: seleziona le righe del workbench, premi **J** (più basso) o **K** (più alto),
  scrivi i semitoni (0–99) e premi Invio. Facoltativo: **Align keys…** propone
  trasposizioni per allineare la classe di altezza a un campione di riferimento.
  Controlla i campioni incerti: restano invariati se non li modifichi tu. Non
  cambia nulla finché non premi **Accept proposal**. Il varispeed cambia sia
  l’altezza sia la durata.
- **Make ×2 variant** (**Ctrl/⌘+D** in entrambi gli elenchi) aggiunge una versione
  un'ottava più alta e di durata dimezzata, mantenendo le righe già nel workbench.
  J/K sostituisce le righe selezionate del workbench. Dalla libreria sostituisce
  le righe corrispondenti già nel workbench, oppure aggiunge la variante se il
  campione sorgente non è presente.
- Scrivi il **nome del kit** (minuscole, es. `dusty-breaks`) e fai clic su **Save as new kit**.

## 5. Trasferisci

**Inviare un kit cancella prima tutti i 100 slot di campioni della Volca.**
Conserva sul computer copie dell’audio che vuoi ricaricare. Un backup dei pattern
non contiene l’audio dei campioni e non può recuperare i campioni cancellati
dallo strumento.

1. Collega il cavo: uscita audio del computer → **SYNC IN** della Volca. Scollega
   casse e cuffie da quell’uscita: il computer riprodurrà segnali di dati. Metti
   in pausa musica, video e notifiche; disattiva EQ e altri processamenti audio.
2. Apri **06 Connections** e scegli quell'uscita in **Transfer output → SYNC IN**.
3. Torna in **Gathering** e fai clic su **Send saved kit to Volca…**. La Browser App
   prepara i segnali e mostra un riepilogo. Leggilo e scegli **Clear & send**
   (oppure **Cancel — keep the Volca as it is**).
4. Attendi **Signals sent**, poi controlla i campioni sulla Volca.

**Signals sent** significa che il computer ha finito di riprodurre i segnali
di trasferimento. Il collegamento SYNC IN non restituisce una conferma alla
Browser App. Controlla i campioni e il loro ordine sulla Volca prima di affidarti
al trasferimento.

Per conservare i segnali preparati, salva prima il kit. **I WAV clear/upload sono
segnali di dati: non ascoltarli attraverso casse o cuffie. Riprodurre i segnali
clear verso SYNC IN cancella tutti i 100 slot.** Scegli **Download SYRO files…**,
poi **Prepare download**. La Browser App scarica uno ZIP e non invia nulla alla Volca.

## Facoltativo: backup e ripristino dei pattern

Il backup salva le dieci memorie di pattern e un’istantanea del pattern in
modifica. Non salva l’audio dei campioni né tutte le impostazioni GLOBAL.

Serve un'interfaccia USB-MIDI (computer → **MIDI IN** della Volca) e un cavo
dall'uscita **cuffie** della Volca all'ingresso audio del computer. In
**Connections** scegli **Backup input** e **MIDI output**, poi in **03 Memory**
scrivi un nome, fai clic su **Capture backup** e conferma con **Start capture**.
Non toccare la Volca per circa due minuti. La prima volta macOS chiede l’accesso
al **microfono**: scegli **Consenti**.
La Browser App salva il banco solo dopo aver ricevuto tutti gli undici frame completi.

Il ripristino sostituisce le memorie selezionate. In **Memory**, apri il banco
salvato, seleziona le memorie da sostituire e scegli **Restore selected memories…**.
Controlla le destinazioni prima di confermare. Per l’istantanea del pattern in
modifica usa **Restore snapshot…** e scegli una destinazione. Dopo **Signals sent**,
controlla sulla Volca una memoria ripristinata.

**Non ascoltare i WAV SYRO dei pattern attraverso casse o cuffie.** Per preparare
i file senza inviarli, scegli **Download selected SYRO files…**. Per l'istantanea
del pattern in modifica scegli prima la memoria di destinazione (1–10), poi
**Download snapshot SYRO…**. Riprodurre quei file verso SYNC IN sostituisce le
memorie indicate.

Per i groove apri **04 Movement**. Scegli le memorie salvate oppure l'istantanea
in modifica del banco con una destinazione esplicita, assegna i template per
parte e premi **Review change plan** prima di salvare. Il catalogo elenca tutti
i sedici offset e distingue i passi misurati, ricostruiti e analitici. La
[guida della Browser App](https://micheledatabeat.github.io/volcastudio-xl-releases/docs/browser.html)
spiega le copie sorgente e i file di rollback (in inglese).

## Se qualcosa non va

| Messaggio | Cosa fare |
| --- | --- |
| *Choose the audio output…* | Vai in **Connections** e scegli l'uscita collegata a SYNC IN. |
| *… is not connected* | Ricollega l'interfaccia, premi **Refresh devices** e sceglila di nuovo. |
| *The audio input could not be opened* | Consenti l'accesso al microfono: macOS **Impostazioni di Sistema → Privacy e sicurezza → Microfono**; Windows **Impostazioni → Privacy e sicurezza → Microfono** (“Consenti alle app desktop di accedere al microfono”). |
| *Google Chrome was not found* | Installa Chrome da google.com/chrome e riapri VolcaStudio XL Browser App. |
| *This window belongs to a closed Browser App session* | Riapri VolcaStudio XL Browser App. |
| L'indicatore è rosso | Togli qualche campione o accorciane alcuni con **K** (più alto = più corto). |
| *Stopped while sending* durante l’invio di un kit | Alcuni slot potrebbero essere cancellati o caricati. Controlla il collegamento, poi reinvia il kit completo quando sei pronto. Per un aggiornamento firmware interrotto, fermati e consulta la guida di installazione del firmware. |
| I campioni sulla Volca suonano male o mancano | Verifica che il cavo vada in SYNC IN, alza il volume dell'uscita (senza distorsione), disattiva effetti/equalizzatori e invia di nuovo. |

**Connections → Check installation** mostra gli strumenti installati e le cartelle
di Studio senza aprire dispositivi audio o MIDI. Non verifica lo strumento o i cavi.

Per finire, fai clic su **Close Browser App** (in alto a destra). Kit e workbench
restano salvati. Dettagli: [guida della Browser App](https://micheledatabeat.github.io/volcastudio-xl-releases/docs/browser.html) (in inglese).
