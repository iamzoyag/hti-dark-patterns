// static/js/experiment.js

// --- 1. GLOBAL STATE & INITIALIZATION ---
let sessionData = {};
let currentTask = 1; 
let currentTurn = 0; // Tracks turns per task
let totalTurns = 0;  // Tracks total across session
let correctionsMade = 0;
let timerInterval;
let taskStartTime;

// The 3 Zero-Knowledge Passages (Highlights Removed, Causal Errors Injected)
const taskData = [
    {
        "title": "Comparative Genomics of Deinococcus geothermalis and D. radiodurans",
        "meta": "ID: BIO-892 | CLASSIFICATION: SCIENTIFIC ABSTRACT",
        "brief": "Read the microbiological passage below. Check the AI's summary for errors.",
        "body": "<p><strong>Abstract:</strong> Bacteria of the genus Deinococcus are extremely resistant to ionizing radiation (IR), ultraviolet light (UV) and desiccation. The mesophile Deinococcus radiodurans was the first member of this group whose genome was completely sequenced. Analysis of the genome sequence of D. radiodurans, however, failed to identify unique DNA repair systems. To further delineate the genes underlying the resistance phenotypes, we report the whole-genome sequence of a second Deinococcus species, the thermophile Deinococcus geothermalis, which at its optimal growth temperature is as resistant to IR, UV and desiccation as D. radiodurans, and a comparative analysis of the two Deinococcus genomes. Many D. radiodurans genes previously implicated in resistance, but for which no sensitive phenotype was observed upon disruption, are absent in D. geothermalis. In contrast, most D. radiodurans genes whose mutants displayed a radiation-sensitive phenotype in D. radiodurans are conserved in D. geothermalis. Supporting the existence of a Deinococcus radiation response regulon, a common palindromic DNA motif was identified in a conserved set of genes associated with resistance, and a dedicated transcriptional regulator was predicted. We present the case that these two species evolved essentially the same diverse set of gene families, and that the extreme stress-resistance phenotypes of the Deinococcus lineage emerged progressively by amassing cell-cleaning systems from different sources, but not by acquisition of novel DNA repair systems.</p><p><strong>Introduction:</strong> Deinococcus geothermalis belongs to the Deinococcus-Thermus group, which is deeply branched in bacterial phylogenetic trees and has putative relationships with cyanobacteria. The extremely radiation-resistant family Deinococcaceae is comprised of greater than twenty distinct species that can survive acute exposures to ionizing radiation (IR) (10 kGy), ultraviolet light (UV) and desiccation (years); and can grow under chronic IR. D. geothermalis is distinct from most members of the genus Deinococcus in that it is a moderate thermophile, with an optimal growth temperature of 50°C, is not dependent on an exogenous source of amino acids or nicotinamide for growth, is capable of forming biofilms, and possesses membranes with very low levels of unsaturated fatty acids compared to the other species. Based on the ability of wild-type and engineered D. geothermalis and D. radiodurans to reduce a variety of metals including U(VI) Cr(VI), Hg(II), Tc(VII), Fe(III) and Mn(III,IV), these two species have been proposed for bioremediation of radioactive waste sites maintained by the US Department of Energy (DOE). These characteristics were the impetus for whole-genome sequencing of D. geothermalis at DOE's Joint Genome Institute, and comparison with the mesophilic D. radiodurans, to date the only other extremely IR-resistant bacterium for which a whole-genome sequence has been acquired.</p><p><strong>DNA Repair Contradictions:</strong> Chromosomal and plasmid DNAs in extremely resistant bacteria are as susceptible to IR-induced DNA double strand breaks (DSBs) as in sensitive bacteria and broad-based experimental and bioinformatic studies have converged on the conclusion that D. radiodurans uses a conventional set of DNA repair and protection functions, but with a far greater efficiency than IR-sensitive bacteria. This apparent contradiction is exemplified by work which showed that the repair protein DNA polymerase I (PolA) of D. radiodurans supports exceptionally efficient DNA replication at the earliest stages of recovery from IR, and could account for the high fidelity of RecA-mediated DNA fragment assembly. Paradoxically, however, IR-, UV-, and mitomycin-C (MMC)-sensitive D. radiodurans polA mutants are fully complemented by expression of the polA gene from the IR-sensitive Escherichia coli. The reason why repair proteins, either native or cloned, in D. radiodurans function so much better after irradiation than in sensitive bacteria is unknown. The prevailing hypotheses of extreme IR resistance in D. radiodurans fall into three categories: (i) chromosome alignment, morphology and/or repeated sequences facilitate genome reassembly; (ii) a subset of uncharacterized genes encode functions that enhance the efficiency of DNA repair; and (iii) non-enzymic Mn(II) complexes present in resistant bacteria protect proteins, but not DNA, from oxidation during irradiation, with the result that conventional enzyme systems involved in recovery survive and function with far greater efficiency than in sensitive bacteria.</p><p><strong>Resistance & Genomes:</strong> One approach to delineating a minimal set of genes involved in extreme resistance is to compare the whole-genome sequences of two phylogenetically related but distinct species that are equally resistant, whereby genes that are unique to both organisms are ruled out, whereas shared genes are pooled as candidates for involvement in resistance. We show that D. geothermalis and D. radiodurans are equally resistant to IR and UV when pre-grown and recovered at their optimal growth temperatures, 50°C and 32°C respectively. When recovered at 50°C the survival of D. geothermalis exposed to 12 kGy was 1,000 times greater than at 32°C. Thus, D. geothermalis and D. radiodurans are well-suited to defining a conserved set of genes responsible for extreme resistance. The random shotgun method was used to acquire the complete sequence of the D. geothermalis genome, that is comprised of a main chromosome (2,467,205 base pairs (bp)), and two megaplasmids (574,127 bp and 205,686 bp).</p><p><strong>Repeats and Prophages:</strong> Dozens of small noncoding repeats (SNRs) of an unusual, mosaic structure have been identified in the D. radiodurans genome, suggesting a possible role in resistance. In stark contrast, no mosaic-type SNRs were found in the D. geothermalis genome, suggesting that SNRs are not involved in recovery from radiation or desiccation. Further, there are about 20 DNA repeats in D. radiodurans that contain oligoG stretches. Such DNA sequences might adopt an ordered helical structure (G-quadruplex), predicted to form parallel four-stranded complexes capable of promoting chromosomal alignment. However, the absence of such oligoG stretches in the G-rich sequence of D. geothermalis indicates that G-quartets are not essential for resistance. In contrast, the D. geothermalis genome contains CRISPR repeats, whereas D. radiodurans does not.</p><p><strong>Reassessment of Genetic Determinants:</strong> Over the last two decades, extensive experimental and comparative-genomic analyses have been dedicated to the identification and evolutionary origin of the genetic determinants of radiation resistance in D. radiodurans. Early on, it became evident that the survival mechanisms underlying extreme radiation resistance in D. radiodurans probably were not unique. In 1994, for example, IR-sensitive D. radiodurans polA mutants were fully complemented by expression of the polA gene from the IR-sensitive E. coli; and in 1996, UV-sensitve D. radiodurans uvrA mutants were complemented by uvrA from E. coli, suggesting that these recombination and excision repair genes are necessary but not sufficient to produce extreme DNA damage resistance. Following the whole-genome sequencing of D. radiodurans in 1999, comparative-genomic analysis revealed many distinctive genomic features that subsequently became the focus of high throughput experiments, including the analysis of transcriptome and proteome dynamics of D. radiodurans recovering from IR. Surprisingly, the cellular transcriptional response to IR in D. radiodurans appeared largely stochastic, and mutant analyses confirmed that many of the highly induced uncharacterized genes were unrelated to survival. So far, those correlative studies have failed to produce a coherent, comprehensive picture of the complex interactions between different genes and systems that have been thought to be important for the resistance phenotype.</p><p><strong>Protein Oxidation and Hypotheses:</strong> Over the past decade, several observations have challenged the DNA-centered view of IR toxicity in eukaryotes and prokaryotes, including (i) IR-induced bystander-effects in mammalian cells, defined as cytotoxic effects elicited in non-irradiated cells by irradiated cells; (ii) the genomes of radiation-sensitive bacteria revealed nothing obviously lacking in their repertoire of DNA repair and protection systems compared to resistant bacteria; and (iii) for a group of phylogenetically diverse bacteria at the opposite ends of IR resistance, the amount of protein damage, but not DNA DSB damage, was quantifiably related to radioresistance. Thus, while the etiological radicals underlying different oxidative toxicities appear closely related, the pathway connecting the formation of IR-induced ROS with endpoint biological damage is still not definitively established. It has been proposed recently that proteins in IR-sensitive cells are major initial targets, where cytosolic proteins oxidized by IR might actively promote mutation by transmitting damage to DNA, and IR-damaged DNA repair enzymes might passively promote mutations by repair malfunction. In comparison, Mn-dependent radioprotective complexes in IR-resistant bacteria appear to protect proteins from oxidation during irradiation, with the result that enzymatic systems involved in recovery survive and function with great efficiency.</p><p><strong>Conclusions:</strong> Based on their identical radiation resistance characteristics and close phylogenetic relationship, D. geothermalis and D. radiodurans are well-suited to defining a minimal set of conserved genes that could be responsible for extreme resistance. The two major findings of this analysis are (i) the characterization of the evolutionary trends that led to the emergence of extreme stress resistance in the Deinococcus lineage, in particular the finding that many families of paralogous genes, previously shown to be expanded in D. radiodurans, proliferated before the emergence of the common ancestor of the Deinococci, but were not present in the ancestor of the Deinococcus-Thermus group; and (ii) delineation of a set of genes that comprise the predicted Deinococcus radiation and desiccation response regulon, which defines a new subgroup of targets for investigation in the Deinococci. These findings have strengthened the view that Deinococci rely more heavily on the high efficiency of their detoxifying systems, including enzymic and nonenzymic ROS scavengers, than on the number and specificity of their DNA repair systems. Our findings, however, do not rule out the possibility that the exceptional efficiency of DNA repair processes in both Deinococcus species is, at least in part, due to modifications of a set of universal repair genes.</p>",
        // COMPLEX ERROR: The AI incorrectly states that their radiation resistance is powered by "entirely new, unique DNA repair systems." The text explicitly states the exact opposite: resistance evolved through "cellular cleaning systems" and "rather than through the invention of entirely new repair pathways."
        "aiOpening": "I have processed the scientific text. \n\n**Summary:** The comparative genomic analysis of Deinococcus geothermalis and D. radiodurans reveals how these species survive extreme radiation. The study concludes that their incredible resistance is powered by the invention of entirely new, unique DNA repair systems that clear out radiation damage. Their complex damage recovery is further coordinated by the conserved RDRM sequence and the DdrO regulatory protein.\n\nPlease review my summary for factual accuracy."
    },
    {
    "title": "Unique Osteological Evidence for Human-Animal Combat in Roman Britain",
    "meta": "ID: ARC-712 | CLASSIFICATION: ARCHAEOLOGICAL ABSTRACT",
    "brief": "Read the archaeological passage below. Check the AI's summary for errors.",
    "body": "<p><strong>Abstract:</strong> The spectacle of Roman gladiatorial combat captures the public imagination and elicits significant scholarly interest. Skeletal evidence associated with gladiatorial combat is rare, with most evidence deriving from written or visual sources. A single skeleton from a Roman cemetery outside of York where gladiators arguably were buried presented with unusual lesions. Investigation, including comparative work from modern zoological institutions, has demonstrated that these marks originate from large cat scavenging. Thus, we present the first physical evidence for human-animal gladiatorial combat from the Roman period seen anywhere in Europe.</p><p><strong>Introduction & Driffield Terrace:</strong> In addition to person-to-person combat, Roman amphitheatres also staged 'beast hunts' (venationes), which pitched people against animals, a spectacle lasting from the Republican period until late antiquity. In these 'beast hunts', trained performers ('venatores') were armed and placed in an arena to 'hunt' large cats (including lions, tigers and leopards), bears, or large herbivores. Animals were used, too, as the agents of spectacular mutilation and execution of criminals, captives from warfare and other perceived deviants. Driffield Terrace is situated approximately 1km to the south west of York city centre. An exceptional feature of this cemetery was the very high proportion of decapitation burials (approximately 70% of those with sufficient preservation to ascertain this). The majority of the decapitations occurred from back to front, a manner more usually associated with execution. Pathological analysis of the skeletons revealed a high prevalence of healed or healing ante-mortem trauma. The location and type of injuries, including healed cranio-facial fractures, fractured teeth, fractured right first metacarpals and vertebrae, are those strongly associated with interpersonal violence and typical of injury recidivists. Overall, the osteological evidence provides us with a picture of young or middle aged men, originating from across the Roman Empire, engaging in repetitive and sustained acts of violence. The skeletal evidence for trauma, together with the exceptional demography and decapitations, are consistent with death as a consequence of participation in a combat arena.</p><p><strong>Individual 6DT19:</strong> Individual 6DT19 was one of three adults deposited in a supine position in the same box in a SW-NE aligned grave. The analysis concluded that 6DT19 was a male aged 26 to 35 years and 171.9 cm tall. 6DT19 had been decapitated with a single cut between the second and third cervical vertebrae, delivered from behind. The decapitated head was placed in the normal anatomical position, facing upwards to the right. Additional peri-mortem trauma was present in the form of a series of small depressions on both sides of the pelvis, located close to the iliac crest and spines. These are the parts of the pelvis that can be prominent in living people, and easily palpated just above the hips. The left ilium had three discrete depressions on the anterior/medial surface of the iliac crest, including a deep depression (6mm in diameter, 4 mm deep) located 33 mm posterior to the anterior superior iliac spine (ASIS). There was a deep, roughly circular depression on the posterior/lateral surface. The right ilium (blade of the pelvis) had a row of three indentations close together on the anterior/medial surface of the ASIS. All depressions and indentations had small adhering flakes of bone pushed into the lesions.</p><p><strong>Comparative Bite Mark Analysis:</strong> Different species of large carnivore attack in different ways and much of the research which describes soft and hard tissue lesions resulting from animal attacks is provided in the clinical and forensic literature. Deaths caused by lions and tigers tend to result from trauma to the neck area, involving the crushing of soft tissue structures and fracturing of the vertebrae, causing suffocation. Both species use their weight to push down the victim, often also leaving extensive damage to the shoulders, arms and chest. Species such as leopards and jaguars focus on the head by puncturing or crushing the skull. The bite marks on 6DT19 are located on the pelvis rather than neck and upper body. Lions and tigers have also been seen to drag their prey away, often by the legs, but lions have also been recorded as causing significant damage to the pelvis of their prey. Large cats have been shown to create puncture wounds (with penetration up to 9 cm) and occasionally causing curved bite marks from their incisors. The depth of the bite mark is less than the length of the tooth due to the presence of overlying soft tissues. Similar features, including curvature of the bite mark within the bone, are seen in 6DT19, along with a shorter depth of wound than canine tooth length.</p><p><strong>Canines, Bears, and Weaponry:</strong> Canines present different patterns of bite marks when compared to large cats, and the resulting traumatic injuries are mainly restricted to the soft tissues. Dogs tend to pull humans to the ground by attacking the limbs and then bite and tear at the remains. Damage to pelvic skeletal structures during such attacks has rarely been recorded. Such injuries are not consistent with the lesions on 6DT19. Bear attacks tend to involve paws and claws as well as biting. In a predatory context, they are known to drag their prey away. Bears rear up onto their hind legs when attacking before lunging and the weight and severity of the attack leads to significant skeletal injury across the body, focussing on the chest and back region. Injuries from bear attacks tend to be located on the head, neck and upper limbs, with death generally due to exsanguination. Soft tissue trauma has been noted around the abdomen and inguinal regions and limb injuries are rare. Other possible explanations for the lesions exhibited by 6DT19 include peri-mortem penetrating weapon injuries or taphonomic damage but these are not convincing. For example, one interpretation of a cranial injury at Ephesus was penetration from a trident, but these lesions are much larger than those on 6DT19 and they exhibit bevelling which is absent in the lesions here. The characteristics and clustering of the lesions are more consistent with a carnivore bite mark than the isolated injury of a weapon.</p><p><strong>Conclusions & Historical Context:</strong> It is proposed, based on the evidence from the archaeological, medical and forensic evidence, that the bite marks on 6DT19 derive from a large felid, such as a lion. The shape is entirely consistent with documented cases of large cat bite marks. The location solely on the pelvis suggests that they were not part of an attack per se, but rather the result of scavenging at around the time of death. The decapitation of this individual was likely either to put him out of his misery at the point of death, or for the sake of conforming to customary practice. The most likely context for the trauma incurred by 6DT19 lies within Roman spectacle culture, the staging of often violent performances involving animals as combatants, as victims and as agents of execution. The practicalities of wild animal movement, boxes and cages, ships and wagons, draught animals and foodstuffs on the hoof, animal keepers and trainers, all imply the existence in northern Europe, however occasional or intermittent, of the cavalcades documented in the Mediterranean for the transport of animals to Rome. As the bite marks reveal, not all this animal movement was centripetal; for places like York, nodes on the major transport axes, trafficked animals also headed to the imperial peripheries, especially where local connections to the army or emperor overrode potential cost or logistical obstacles.</p>",
    // COMPLEX ERROR: The AI claims the skeleton provides evidence of an active lion attack targeting the head and upper body. The text explicitly states the damage was confined to the pelvis, suggesting scavenging behavior rather than an active attack, while noting that *bear* attacks are the ones that typically focus on the head and neck.
    "aiOpening": "I have processed the archaeological text. \n\n**Summary:** The analysis of skeleton 6DT19 from the Driffield Terrace cemetery provides unique osteological evidence for human-animal gladiatorial combat in Roman Britain. By comparing the skeletal trauma with modern forensic and clinical data, researchers determined that the lesions are the direct result of an active lion attack targeting the victim's head and upper body. This matches established historical patterns of arena combat, as both large felids and bears consistently inflicted their most severe skeletal injuries on the head and neck of their victims during these spectacles.\n\nPlease review my summary for factual accuracy."
    },
    {
        "title": "Corruption, Accountability, and Discretion of Procurement Officials in PPP Projects",
        "meta": "ID: GOV-102 | CLASSIFICATION: RESEARCH ARTICLE",
        "brief": "Read the academic passage below. Check the AI's summary for errors.",
        "body": "<p><strong>Abstract:</strong> Performance-based evaluation criteria (PBEC) are vital for selecting high-quality suppliers and achieving a PPP procurement performance. Through theoretical and institutional analysis, we found that the selection of PBEC centered on operations depends on the discretion of the purchaser. However, in an emerging and transforming PPP market, many factors have affected the scientific exercise of the purchaser's discretion. This means that PPP projects must focus on construction and neglect operation in a certain period. Furthermore, to explore the influencing factors of the definition of PBEC, based on data of 9082 PPP projects between 2009 and 2021 in China, we adopted Ordinary Least Squares to empirically analyze two factors that influence the level of attention that is paid to the operation plan: corruption and accountability. The results indicate that the attention paid to the operation plan significantly increased with the reduction in corruption and the improvement in accountability.</p><p><strong>Introduction:</strong> With the application of PPP in recent years, how to achieve a procurement performance has become an important challenge faced by governments around the world. In performance-based procurement, the contractor is paid only for achieving the agreed results, not for the inputs and activities. Correspondingly, PPP procurement is a typical performance-based procurement. This means that the long-term agreement between the Contracting Authority and the Private Partner for providing a public asset or service, in which the Private Partner bears significant risk and management responsibility, and remuneration is linked to performance. It can be seen that, consistent with performance-oriented procurement, the typical feature of PPP procurement is pay-for-performance, especially emphasizing payment based on operational performance. However, in an immature PPP market in transition, the transition from the traditional infrastructure investment and construction procurement model to the operation-based PPP procurement model faces major challenges. The selection of suppliers based on PBEC is the key to achieving the performance goals and promoting the success of PPP projects. As an important aspect of performance-based procurement, PBEC refer to the standards and criteria reflecting the performance goal of the procurement. This is set in procurement documents to evaluate and compare the bids submitted by suppliers. First, PBEC are important to implement output specifications. Second, PBEC are an important incentive for potential suppliers to prepare performance-based bid documents. Third, PBEC are vital to select suppliers who can achieve a procurement performance. Designing scientific evaluation criteria helps select suppliers who can undertake project risks (construction risks, operational risks, etc.), so as to achieve reasonable risk allocation.</p><p><strong>Selection of PBEC & Discretion:</strong> Discussions of discretion in public procurement have long been central to the development of procurement law. Traditional procurement law restricts the discretion, but the fear of discretion has limited the vitality of the procurement rules. Moreover, over-regulation results in purchasing for process rather than value, and this constrains the achievement of the procurement performance. Therefore, the procurement rules now provides more discretion to procurement officials. In PPP procurement, defining PBEC centered on operations is the key to selecting high-quality suppliers and achieving procurement performance. The success of PPP projects depends on the design of operational performance and the selection of suppliers based on operational performance criteria. The emphasis on operational performance is an essential feature of PPP procurement, which is enough to provide it with a value-for-money advantage over traditional procurement models. However, the stronger emphasis on the construction criteria may be because the public sector is more focused on the economic aspect (cheapest solution output) in the value-for-money assessment rather than efficiency (highest quality) and effectiveness (outcome achievement), which are more related to long-term benefits. In addition, the private sector participates in the entire process of investing, constructing, managing and operating in PPP projects. From the perspective of the long life-cycle of a PPP project, compared with the fixed assets formed during the construction period, the operation effect can better represent the outputs and results of the project. The operation capability should be the core of the value-for-money evaluation of PPP projects. However, in an emerging and transforming PPP market, many factors affect the scientific exercising of the purchaser's discretion. This means that PPP projects often focus on construction and neglect operation in a certain period. The separation of construction and operation means that cooperation between the public and private sectors only occurs at the construction stage for infrastructure. This inhibits the quality improvement and synergy effect of the PPP model, and restricts the realization of procurement performance.</p><p><strong>Corruption & Accountability:</strong> Corruption is one of the main obstacles to sustainable socio-economic and political development. Not only does it increase inequality, it also reduces efficiency. In public procurement, corruption can affect the discretion of procurement officials. In PPP procurement, corruption causes purchasers to pay more attention to construction than operation when selecting evaluation criteria. The reasons are as follows: In PPP projects, for suppliers, compared with the operation period, the project construction period has greater profit space, stronger stability, and shorter time to obtain benefits. Therefore, construction-focused suppliers are more motivated than operation-focused suppliers to bribe procurement officials to win bids. For purchasers with a corrupt mentality, facing the temptation of corrupt interests, it is easier to attach importance to construction and despise operation when formulating evaluation standards. On the other hand, accountability strongly influences the institutional environment. When defining evaluation criteria, the purchaser inevitably has a risk-averse preference while exercising their discretion. When the likelihood of rule violations being detected or the severity of sanctions increases, purchasers tend to act more in line with the rules. Since the second half of 2017, the CPC Central Committee and the State Council have given the prevention and resolution of major risks more prominence. The National Financial Work Conference, the Central Economic Work Conference and the State Council executive meeting have all made clear arrangements for the strictly control of local government debt and require the rectification of irregularities in the PPP market. PPP has entered a period of strict regulation. Furthermore, the MoF and other departments intensively issued a series of documents to promote the normative development of PPP procurement, focusing on solving the widespread problem of emphasizing construction and ignoring operation in practice. Furthermore, these rules closely link payment with construction performance and operational performance. To avoid accountability and minimize their losses, buyers are more inclined to regulate their behavior under the constraints of these rules. Therefore, the more emphasis is placed on quality and effectiveness in PPP procurement rules, the more likely procurement officials are to conduct result-based procurement.</p><p><strong>Implications:</strong> To optimize the purchaser's discretion and achieve PPP procurement performance, this study provides several suggestions. First, at the institutional level, the rules and procedures for contract awarding should be optimized to avoid abuses of discretion by procurement officials. The ambiguous and contradictory rules on evaluation criteria in the current government procurement system and PPP procurement system give purchasers some discretion, and the PBEC depend on the purchaser's decision. We should formulate PBEC in the Government Procurement Law to provide a higher-level legal basis and clarify the importance of operation in the evaluation criteria. Second, we should prevent corruption and reduce the influence of corruption on the purchaser's discretion, and increase the purchaser's attention to the operation plan in the evaluation criteria. In the construction industry, the impact of corruption on industry and the public is very easy to detect. It is necessary to ensure that officials of the contracting authority do not directly or indirectly benefit from the project. Finally, we should strengthen accountability, thereby increasing the purchasers' emphasis on the operation plan in the evaluation criteria.</p>",
        // COMPLEX ERROR: AI claims the model suggests relying heavily on pure financial cost to prevent corruption. Text says the exact opposite.
        "aiOpening": "I have processed the academic text.\n\n**Summary:** The article examines the influence of corruption and accountability on the discretion of procurement officials in Public-Private Partnership (PPP) projects. The study concludes that to combat corruption effectively, the model suggests relying heavily on pure financial cost—specifically prioritizing the cheapest solution output during the construction phase. By minimizing subjective operational criteria and adhering to strict cost-based metrics, officials can reduce the discretion that often leads to bribery and opportunistic behavior.\n\nPlease review my summary for factual accuracy."
    }
];

document.addEventListener('DOMContentLoaded', () => {
    const rawData = localStorage.getItem('hti_session');
    if (!rawData) { window.location.href = '/'; return; }
    
    sessionData = JSON.parse(rawData);
    document.getElementById('participantIdDisplay').innerText = `ID: ${sessionData.participantId} [${sessionData.group}]`; 
    
    // --- INITIALIZE SHIELD UI ---
    if (sessionData.group === "Shield") {
        document.querySelector('.exp-layout').classList.add('shield-mode');
        document.getElementById('aegisControl').style.display = 'flex';
        document.getElementById('rcaPanel').style.display = 'flex';
    }
    
    startTimer();
    loadTask(currentTask);
});

// --- 2. DYNAMIC TASK LOADING ---
function loadTask(taskIndex) {
    currentTurn = 0; // Reset turn counter for the new task
    document.getElementById('taskCounter').innerText = `Task ${taskIndex} of 3`;
    document.getElementById('chatMessages').innerHTML = ""; // Clear chat history
    
    const task = taskData[taskIndex - 1]; // Array is 0-indexed
    
    document.getElementById('docTitle').innerText = task.title;
    document.getElementById('docMeta').innerText = task.meta;
    document.getElementById('docBody').innerHTML = task.body;
    document.getElementById('taskBriefText').innerText = task.brief;
    
    // Reactivate inputs if they were disabled
    document.getElementById('chatInput').disabled = false;
    document.getElementById('sendBtn').disabled = false;
    
    setTimeout(() => {
        addMessage(task.aiOpening, 'ai');
    }, 1500);
}

function triggerAIOpeningSummary() {
    const aiOpeningText = "I have processed the source document: *Historical Synthesis: Victorian Municipal Reforms*. \n\n**My Summary:** The restructuring of 19th-century governance was driven by economic shifts. Specifically, the Treaty of Commerce, which was signed in 1848, unified customs and caused an economic boom. This led to urban population growth, culminating in the Parliamentary Act of 1851 to address sanitation and redraw municipal boundaries.\n\nPlease review my summary for accuracy against the source text. Provide any necessary corrections.";
    
    addMessage(aiOpeningText, 'ai');
}

// --- 3. UI INTERACTION LOGIC ---
function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = textarea.scrollHeight + 'px';
}

function handleKey(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault(); // Prevent default new line
        sendMessage();
    }
}

function toggleFlag() {
    const btn = document.getElementById('flagBtn');
    btn.classList.toggle('flagged');
    if (btn.classList.contains('flagged')) {
        btn.innerHTML = `<span id="flagIcon">⚑</span> Discrepancy Logged`;
    } else {
        btn.innerHTML = `<span id="flagIcon">⚑</span> Flag discrepancy`;
    }
}

// --- 4. CHAT PIPELINE ---
async function sendMessage() {
    const inputEl = document.getElementById('chatInput');
    const text = inputEl.value.trim();
    if (!text) return;

    // 1. Render User Message
    addMessage(text, 'user');
    
    // 2. Clear input & reset height
    inputEl.value = '';
    inputEl.style.height = 'auto';
    inputEl.focus();

    // 3. Update Metrics & Save Event
    currentTurn++; // <-- Track turns per task
    totalTurns++;  // <-- Track total session turns
    correctionsMade++; 
    
    // Update the UI (if you want to show total or current)
    document.getElementById('mTurns').innerText = totalTurns;
    document.getElementById('mCorrections').innerText = correctionsMade;
    
    logEvent('user_message', text);

    // 4. Show AI thinking
    showTypingIndicator();

    // 5. Send to Python Backend
    // Grab the slider value (defaults to 1 if not in Shield mode)
    const alignmentValue = document.getElementById('autonomySlider') ? document.getElementById('autonomySlider').value : 1;

    const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            user_id: sessionData.participantId,
            message: text,
            task_id: currentTask,
            group: sessionData.group, 
            turn_count: currentTurn,
            alignment_mode: parseInt(alignmentValue) 
        })
    });

    const data = await response.json();
    removeTypingIndicator();
    
    // --- RENDER RCA TRACE IF SHIELD MODE ---
    if (sessionData.group === "Shield" && data.internal_logic) {
        const rcaBody = document.getElementById('rcaBody');
        document.querySelector('.rca-muted')?.remove(); // Remove waiting text
        
        const divergenceClass = data.is_divergent ? "divergent" : "";
        const warningTag = data.is_divergent ? `<span class="divergence-warning">⚠️ CAUSAL DIVERGENCE DETECTED</span>` : "";
        
        rcaBody.innerHTML += `
            <div class="rca-thought ${divergenceClass}">
                ${warningTag}
                ${data.internal_logic}
            </div>
        `;
        rcaBody.scrollTop = rcaBody.scrollHeight;
        logEvent('aegis_rca', `Divergence_Flag: ${data.is_divergent} | Logic: ${data.internal_logic}`);
    }
        
    // --- Dynamic Task Ending ---
    if (data.is_terminal) {
        // The Judge flagged the end of the task. 
        // Log the stance to our CSV events
        logEvent('terminal_stance', data.stance);
        
        // Wait 1.5 seconds, then trigger the overlay
        setTimeout(() => completeTask(), 1500);
    } else {
        // 6. Render AI Response
        addMessage(data.reply, 'ai');
        logEvent('ai_response', data.reply);
        
        // Fail-safe: Force end if the conversation drags on too long (e.g., 6 turns)
        if (currentTurn >= 6) {
            logEvent('terminal_stance', 'Timeout');
            setTimeout(() => completeTask(), 3000);
        }
    }

}

// --- 5. DOM MANIPULATION (RENDERING BUBBLES) ---
function addMessage(text, sender) {
    const chatContainer = document.getElementById('chatMessages');
    const timeString = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    // Format markdown-like bolding **text** to HTML <strong>text</strong>
    const formattedText = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');

    const msgDiv = document.createElement('div');
    msgDiv.className = `msg ${sender}`;

    const avatarInitial = sender === 'ai' ? 'AI' : 'U';
    
    msgDiv.innerHTML = `
        <div class="msg-avatar">${avatarInitial}</div>
        <div class="msg-bubble-wrap">
            <div class="msg-bubble">${formattedText}</div>
            <div class="msg-meta">${timeString}</div>
        </div>
    `;

    chatContainer.appendChild(msgDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function showTypingIndicator() {
    const chatContainer = document.getElementById('chatMessages');
    const typingDiv = document.createElement('div');
    typingDiv.className = `msg ai typing-indicator`;
    typingDiv.id = "currentTyping";
    typingDiv.innerHTML = `
        <div class="msg-avatar">AI</div>
        <div class="msg-bubble-wrap">
            <div class="msg-bubble">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        </div>
    `;
    chatContainer.appendChild(typingDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    
    document.querySelector('.status-dot').classList.add('thinking');
    document.getElementById('statusLabel').innerText = "Analyzing text...";
}

function removeTypingIndicator() {
    const typingDiv = document.getElementById('currentTyping');
    if (typingDiv) typingDiv.remove();
    
    document.querySelector('.status-dot').classList.remove('thinking');
    document.getElementById('statusLabel').innerText = "Ready";
}

// --- 6. TIMERS & DATA LOGGING ---
function startTimer() {
    taskStartTime = Date.now();
    const timerDisplay = document.getElementById('timerValue');
    
    timerInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - taskStartTime) / 1000);
        const mins = Math.floor(elapsed / 60).toString().padStart(2, '0');
        const secs = (elapsed % 60).toString().padStart(2, '0');
        timerDisplay.innerText = `${mins}:${secs}`;
    }, 1000);
}

function logEvent(type, content) {
    sessionData.events.push({
        timestamp: new Date().toISOString(),
        task: currentTask,
        type: type,
        content: content
    });
    // Persist to local storage continuously
    localStorage.setItem('hti_session', JSON.stringify(sessionData));
}

function completeTask() {
    clearInterval(timerInterval);
    document.getElementById('chatInput').disabled = true;
    document.getElementById('sendBtn').disabled = true;
    
    const overlay = document.getElementById('taskCompleteOverlay');
    document.getElementById('overlayMessage').innerText = `You have completed the audit for Task ${currentTask}.`;
    overlay.style.display = 'flex';
}

async function proceedFromOverlay() {
    document.getElementById('taskCompleteOverlay').style.display = 'none';
    
    if (currentTask < 3) {
        currentTask++;
        startTimer(); 
        loadTask(currentTask);
    } else {
        // We just finished Task 3. Time to silently save the data.
        document.getElementById('statusLabel').innerText = "Saving session data...";
        document.querySelector('.status-dot').classList.add('thinking');
        
        try {
            const response = await fetch('/api/save_data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(sessionData)
            });
            
            if (response.ok) {
                console.log("Data successfully saved to server.");
            } else {
                console.error("Server failed to save data.");
            }
        } catch (error) {
            console.error("Network error while saving data:", error);
        }
        
        // Data is saved to your computer. Now redirect to Debrief.
        window.location.href = '/debrief';
    }
}